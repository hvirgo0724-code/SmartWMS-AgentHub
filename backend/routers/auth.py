"""认证模块：登录/注销/注册/个人信息/验证码改密/重置申请"""
import random
import time
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from database import query, query_one, execute, execute_return_id, add_log, get_conn
from security import verify_password, create_token, hash_password
from deps import get_current_user, require_perm, ok, fail

router = APIRouter(prefix="/auth", tags=["认证"])

# 密码重置申请表（幂等创建，兼容已有库）
with get_conn() as _conn:
    _cur = _conn.cursor()
    _cur.execute("""CREATE TABLE IF NOT EXISTS password_reset_request (
        id INT AUTO_INCREMENT PRIMARY KEY,
        user_id INT NOT NULL,
        reason VARCHAR(255) DEFAULT '',
        status VARCHAR(20) DEFAULT 'pending' COMMENT 'pending/approved/rejected',
        handler_id INT DEFAULT NULL,
        handle_time DATETIME DEFAULT NULL,
        create_time DATETIME DEFAULT CURRENT_TIMESTAMP
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
    _conn.commit()

# 手机验证码（内存存储，5分钟有效）：phone -> (code, expire_ts)
SMS_CODES = {}

# 迁移：sys_user 表补充身份证号列（幂等）
with get_conn() as _conn:
    _cur = _conn.cursor()
    _cur.execute("""SELECT COUNT(*) FROM information_schema.COLUMNS
                    WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='sys_user' AND COLUMN_NAME='id_card'""")
    if list(_cur.fetchone().values())[0] == 0:
        _cur.execute("ALTER TABLE sys_user ADD COLUMN id_card VARCHAR(18) DEFAULT NULL COMMENT '身份证号' AFTER phone")
    _conn.commit()


def _validate_id_card(id_card: str) -> str:
    """校验18位身份证号（含校验位），返回错误信息（None 表示通过）"""
    if len(id_card) != 18:
        return "身份证号必须为18位"
    weights = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2]
    codes = "10X98765432"
    try:
        s = sum(int(id_card[i]) * weights[i] for i in range(17))
        if codes[s % 11] != id_card[17].upper():
            return "身份证号校验位不正确，请检查输入"
    except ValueError:
        return "身份证号格式不正确"
    return None


def _validate_phone(phone: str) -> str:
    """校验大陆手机号格式，返回错误信息（None 表示通过）"""
    if not (len(phone) == 11 and phone.startswith("1") and phone[1:].isdigit()):
        return "手机号格式不正确（11位，以1开头）"
    return None


class LoginBody(BaseModel):
    username: str
    password: str


class RegisterBody(BaseModel):
    username: str
    password: str
    real_name: str = ""
    phone: str = ""
    id_card: str = ""
    code: str = ""


class ChangePwdBody(BaseModel):
    old_password: str
    new_password: str


def _user_token_payload(user):
    roles = query("SELECT r.role_code FROM sys_role r JOIN sys_user_role ur ON ur.role_id=r.id WHERE ur.user_id=%s", (user["id"],))
    perms = query("SELECT DISTINCT p.perm_code FROM sys_permission p JOIN sys_role_permission rp ON rp.perm_id=p.id JOIN sys_user_role ur ON ur.role_id=rp.role_id WHERE ur.user_id=%s", (user["id"],))
    role_codes = [r["role_code"] for r in roles]
    perm_codes = [p["perm_code"] for p in perms]
    if "admin" in role_codes:  # 管理员拥有全部权限
        perm_codes = ["*"]
    return {"uid": user["id"], "username": user["username"], "roles": role_codes, "perms": perm_codes}


@router.post("/login")
def login(body: LoginBody):
    user = query_one("SELECT * FROM sys_user WHERE username=%s", (body.username,))
    if not user or not verify_password(body.password, user["password_hash"]):
        return fail("用户名或密码错误")
    if user.get("status") != 1:
        return fail("账号已被禁用")
    payload = _user_token_payload(user)
    token = create_token(payload)
    user["ip"] = ""
    add_log(None, {"id": user["id"], "username": user["username"], "ip": ""}, "认证", "登录", f"用户 {user['username']} 登录系统")
    return ok({"token": token, "user": {"id": user["id"], "username": user["username"], "real_name": user["real_name"], "roles": payload["roles"], "perms": payload["perms"]}})


# ---------- 免登录：短信验证码登录 / 忘记密码 ----------
def _issue_sms_code(phone: str) -> str:
    """生成并暂存验证码，返回明文（演示环境无短信通道）"""
    code = f"{random.randint(100000, 999999)}"
    SMS_CODES[phone] = (code, time.time() + 300)
    return code


def _check_sms_code(phone: str, code: str) -> str:
    """校验验证码，返回错误信息（None 表示通过）"""
    rec = SMS_CODES.get(phone)
    if not rec:
        return "请先获取验证码"
    real, expire = rec
    if time.time() > expire:
        SMS_CODES.pop(phone, None)
        return "验证码已过期，请重新获取"
    if code.strip() != real:
        return "验证码错误"
    SMS_CODES.pop(phone, None)
    return None


class SmsLoginCodeBody(BaseModel):
    phone: str


@router.post("/sms-login-code")
def sms_login_code(body: SmsLoginCodeBody):
    """登录页：向绑定该手机号的用户发送验证码"""
    phone = body.phone.strip()
    user = query_one("SELECT * FROM sys_user WHERE phone=%s AND status=1", (phone,))
    if not user:
        return fail("该手机号未绑定任何启用账号")
    code = _issue_sms_code(phone)
    add_log(None, {"id": user["id"], "username": user["username"]}, "认证", "获取登录验证码",
            f"用户 {user['username']} 获取短信登录验证码")
    return ok({"code": code}, msg="验证码已发送")


class SmsLoginBody(BaseModel):
    phone: str
    code: str


@router.post("/login-by-sms")
def login_by_sms(body: SmsLoginBody):
    """登录页：手机号 + 验证码直接登录"""
    phone = body.phone.strip()
    user = query_one("SELECT * FROM sys_user WHERE phone=%s AND status=1", (phone,))
    if not user:
        return fail("该手机号未绑定任何启用账号")
    err = _check_sms_code(phone, body.code)
    if err:
        return fail(err)
    payload = _user_token_payload(user)
    token = create_token(payload)
    add_log(None, {"id": user["id"], "username": user["username"]}, "认证", "短信登录",
            f"用户 {user['username']} 通过短信验证码登录")
    return ok({"token": token, "user": {"id": user["id"], "username": user["username"], "real_name": user["real_name"], "roles": payload["roles"], "perms": payload["perms"]}})


class ForgotCodeBody(BaseModel):
    username: str
    phone: str


@router.post("/forgot-code")
def forgot_code(body: ForgotCodeBody):
    """登录页-忘记密码：校验用户名与手机号匹配后发送验证码"""
    user = query_one("SELECT * FROM sys_user WHERE username=%s", (body.username.strip(),))
    if not user or (user.get("phone") or "").strip() != body.phone.strip():
        return fail("用户名与手机号不匹配")
    if user.get("status") != 1:
        return fail("账号已被禁用")
    code = _issue_sms_code(body.phone.strip())
    add_log(None, {"id": user["id"], "username": user["username"]}, "认证", "获取重置验证码",
            f"用户 {user['username']} 获取忘记密码验证码")
    return ok({"code": code}, msg="验证码已发送")


class ForgotResetBody(BaseModel):
    username: str
    phone: str
    code: str
    new_password: str


@router.post("/forgot-reset")
def forgot_reset(body: ForgotResetBody):
    """登录页-忘记密码：验证码 + 新密码重置"""
    if len(body.new_password) < 6:
        return fail("新密码至少6位")
    user = query_one("SELECT * FROM sys_user WHERE username=%s", (body.username.strip(),))
    if not user or (user.get("phone") or "").strip() != body.phone.strip():
        return fail("用户名与手机号不匹配")
    err = _check_sms_code(body.phone.strip(), body.code)
    if err:
        return fail(err)
    execute("UPDATE sys_user SET password_hash=%s WHERE id=%s", (hash_password(body.new_password), user["id"]))
    add_log(None, {"id": user["id"], "username": user["username"]}, "认证", "忘记密码重置",
            f"用户 {user['username']} 通过忘记密码流程重置了密码")
    return ok(msg="密码重置成功，请使用新密码登录")


@router.post("/forgot-apply")
def forgot_apply(body: ForgotCodeBody):
    """登录页-忘记密码：向管理员申请重置（需验证用户名与手机号匹配）"""
    user = query_one("SELECT * FROM sys_user WHERE username=%s", (body.username.strip(),))
    if not user or (user.get("phone") or "").strip() != body.phone.strip():
        return fail("用户名与手机号不匹配")
    pend = query_one("SELECT id FROM password_reset_request WHERE user_id=%s AND status='pending'", (user["id"],))
    if pend:
        return fail("您已有待处理的重置申请，请耐心等待管理员审核")
    execute("INSERT INTO password_reset_request (user_id, reason) VALUES (%s,%s)",
            (user["id"], "登录页忘记密码，申请重置"))
    add_log(None, {"id": user["id"], "username": user["username"]}, "认证", "重置申请",
            f"用户 {user['username']} 从登录页申请重置密码")
    return ok(msg="申请已提交，管理员审核通过后密码将重置为 123456")


@router.post("/logout")
def logout(user: dict = Depends(get_current_user)):
    add_log(None, user, "认证", "注销", f"用户 {user['username']} 退出登录")
    return ok(msg="已注销")


class RegisterCodeBody(BaseModel):
    phone: str


@router.post("/register-code")
def register_code(body: RegisterCodeBody):
    """注册页：向新手机号发送验证码（要求手机号未被绑定）"""
    phone = body.phone.strip()
    err = _validate_phone(phone)
    if err:
        return fail(err)
    if query_one("SELECT id FROM sys_user WHERE phone=%s", (phone,)):
        return fail("该手机号已被注册，请直接登录或换绑其他手机号")
    code = _issue_sms_code(phone)
    return ok({"code": code}, msg="验证码已发送")


@router.post("/register")
def register(body: RegisterBody):
    username = body.username.strip()
    phone = (body.phone or "").strip()
    id_card = (body.id_card or "").strip().upper()
    if query_one("SELECT id FROM sys_user WHERE username=%s", (username,)):
        return fail("用户名已存在")
    if len(body.password) < 6:
        return fail("密码至少6位")
    err = _validate_phone(phone)
    if err:
        return fail(err)
    err = _validate_id_card(id_card)
    if err:
        return fail(err)
    if query_one("SELECT id FROM sys_user WHERE phone=%s", (phone,)):
        return fail("该手机号已被注册")
    if query_one("SELECT id FROM sys_user WHERE id_card=%s AND id_card IS NOT NULL AND id_card!=''", (id_card,)):
        return fail("该身份证号已注册过账号")
    err = _check_sms_code(phone, (body.code or "").strip())
    if err:
        return fail(err)
    uid = execute_return_id(
        "INSERT INTO sys_user (username, password_hash, real_name, phone, id_card) VALUES (%s,%s,%s,%s,%s)",
        (username, hash_password(body.password), body.real_name or username, phone, id_card),
    )
    # 默认分配 viewer 角色
    role = query_one("SELECT id FROM sys_role WHERE role_code='viewer'")
    if role:
        execute("INSERT INTO sys_user_role (user_id, role_id) VALUES (%s,%s)", (uid, role["id"]))
    add_log(None, {"id": uid, "username": username}, "认证", "注册", f"新用户 {username} 注册（手机号 {phone}）")
    return ok({"id": uid}, "注册成功")


@router.get("/me")
def me(user: dict = Depends(get_current_user)):
    roles = query("SELECT r.role_name FROM sys_role r JOIN sys_user_role ur ON ur.role_id=r.id WHERE ur.user_id=%s", (user["id"],))
    return ok({**{k: user.get(k) for k in ("id", "username", "real_name", "phone", "email")},
               "roles": [r["role_name"] for r in roles],
               "role_codes": user.get("roles", []),
               "perms": user.get("perms", [])})


# 换绑验证码存储：("sms", 手机号) / ("email", 邮箱) -> (code, expire_ts)
REBIND_CODES = {}


def _issue_rebind_code(kind: str, target: str) -> str:
    """生成换绑验证码（演示环境无短信/邮件通道，明文返回由前端展示）"""
    code = f"{random.randint(100000, 999999)}"
    REBIND_CODES[(kind, target)] = (code, time.time() + 300)
    return code


def _check_rebind_code(kind: str, target: str, code: str) -> str:
    """校验换绑验证码，返回错误信息（None 表示通过，通过即失效）"""
    rec = REBIND_CODES.get((kind, target))
    if not rec:
        return "请先获取验证码"
    real, expire = rec
    if time.time() > expire:
        REBIND_CODES.pop((kind, target), None)
        return "验证码已过期，请重新获取"
    if (code or "").strip() != real:
        return "验证码错误"
    REBIND_CODES.pop((kind, target), None)
    return None


class RebindSmsBody(BaseModel):
    new_phone: str


@router.post("/rebind/sms-code")
def rebind_sms_code(body: RebindSmsBody, user: dict = Depends(get_current_user)):
    """换绑手机号：向新手机号发送验证码"""
    phone = body.new_phone.strip()
    if not phone or len(phone) != 11 or not phone.isdigit():
        return fail("请输入正确的11位手机号")
    if phone == (user.get("phone") or "").strip():
        return fail("新手机号与当前绑定的一致，无需换绑")
    if query_one("SELECT id FROM sys_user WHERE phone=%s AND id<>%s", (phone, user["id"])):
        return fail("该手机号已被其他账号绑定")
    code = _issue_rebind_code("sms", phone)
    add_log(None, user, "认证", "换绑手机验证码", f"用户 {user['username']} 申请换绑手机号 {phone[:3]}****{phone[-4:]}")
    return ok({"code": code}, msg="验证码已发送至新手机号")


class RebindEmailBody(BaseModel):
    new_email: str


@router.post("/rebind/email-code")
def rebind_email_code(body: RebindEmailBody, user: dict = Depends(get_current_user)):
    """换绑邮箱：向新邮箱发送验证码"""
    email = body.new_email.strip()
    if not email or "@" not in email or "." not in email.split("@")[-1]:
        return fail("请输入正确的邮箱地址")
    if email == (user.get("email") or "").strip():
        return fail("新邮箱与当前绑定的一致，无需换绑")
    if query_one("SELECT id FROM sys_user WHERE email=%s AND id<>%s", (email, user["id"])):
        return fail("该邮箱已被其他账号绑定")
    code = _issue_rebind_code("email", email)
    add_log(None, user, "认证", "换绑邮箱验证码", f"用户 {user['username']} 申请换绑邮箱 {email}")
    return ok({"code": code}, msg="验证码已发送至新邮箱")


class ProfileBody(BaseModel):
    phone: str = ""
    sms_code: str = ""
    email: str = ""
    email_code: str = ""


@router.put("/me")
def update_profile(body: ProfileBody, user: dict = Depends(get_current_user)):
    """换绑手机号/邮箱：变更字段须携带对应验证码；职位与权限只能由管理员设置"""
    old_phone = (user.get("phone") or "").strip()
    old_email = (user.get("email") or "").strip()
    new_phone = (body.phone or "").strip()
    new_email = (body.email or "").strip()

    phone_changed = new_phone != old_phone
    email_changed = new_email != old_email
    if not phone_changed and not email_changed:
        return fail("资料未变更，无需保存")

    # 校验换绑手机号
    if phone_changed:
        if not new_phone:
            return fail("手机号不能为空")
        if len(new_phone) != 11 or not new_phone.isdigit():
            return fail("请输入正确的11位手机号")
        if query_one("SELECT id FROM sys_user WHERE phone=%s AND id<>%s", (new_phone, user["id"])):
            return fail("该手机号已被其他账号绑定")
        err = _check_rebind_code("sms", new_phone, body.sms_code)
        if err:
            return fail(f"手机换绑失败：{err}")

    # 校验换绑邮箱
    if email_changed:
        if not new_email:
            return fail("邮箱不能为空")
        if "@" not in new_email or "." not in new_email.split("@")[-1]:
            return fail("请输入正确的邮箱地址")
        if query_one("SELECT id FROM sys_user WHERE email=%s AND id<>%s", (new_email, user["id"])):
            return fail("该邮箱已被其他账号绑定")
        err = _check_rebind_code("email", new_email, body.email_code)
        if err:
            return fail(f"邮箱换绑失败：{err}")

    execute("UPDATE sys_user SET phone=%s, email=%s WHERE id=%s", (new_phone, new_email, user["id"]))
    changed = "、".join(filter(None, [phone_changed and "手机号", email_changed and "邮箱"]))
    add_log(None, user, "认证", "换绑资料", f"用户 {user['username']} 换绑了{changed}")
    return ok(msg=f"{changed}换绑成功")


@router.post("/password/sms-code")
def send_sms_code(user: dict = Depends(get_current_user)):
    """向当前用户绑定手机号发送验证码（演示环境直接返回验证码）"""
    phone = (user.get("phone") or "").strip()
    if not phone:
        return fail("您未绑定手机号，请先在个人中心绑定手机号")
    code = f"{random.randint(100000, 999999)}"
    SMS_CODES[phone] = (code, time.time() + 300)
    add_log(None, user, "认证", "获取验证码", f"用户 {user['username']} 获取手机验证码")
    # 演示系统无短信通道，验证码直接返回由前端展示
    return ok({"phone": phone, "code": code}, msg="验证码已发送")


class SmsResetBody(BaseModel):
    code: str
    new_password: str


@router.post("/password/reset-by-sms")
def reset_by_sms(body: SmsResetBody, user: dict = Depends(get_current_user)):
    """通过手机验证码重置自己的密码（忘记原密码时使用）"""
    if len(body.new_password) < 6:
        return fail("新密码至少6位")
    phone = (user.get("phone") or "").strip()
    rec = SMS_CODES.get(phone)
    if not rec:
        return fail("请先获取验证码")
    code, expire = rec
    if time.time() > expire:
        SMS_CODES.pop(phone, None)
        return fail("验证码已过期，请重新获取")
    if body.code.strip() != code:
        return fail("验证码错误")
    SMS_CODES.pop(phone, None)
    execute("UPDATE sys_user SET password_hash=%s WHERE id=%s", (hash_password(body.new_password), user["id"]))
    add_log(None, user, "认证", "验证码改密", f"用户 {user['username']} 通过手机验证码重置了密码")
    return ok(msg="密码重置成功")


class ResetApplyBody(BaseModel):
    reason: str = ""


@router.post("/reset-requests")
def apply_reset(body: ResetApplyBody, user: dict = Depends(get_current_user)):
    """向管理员提交密码重置申请"""
    pend = query_one("SELECT id FROM password_reset_request WHERE user_id=%s AND status='pending'", (user["id"],))
    if pend:
        return fail("您已有待处理的重置申请，请耐心等待管理员审核")
    execute("INSERT INTO password_reset_request (user_id, reason) VALUES (%s,%s)", (user["id"], body.reason.strip()))
    add_log(None, user, "认证", "重置申请", f"用户 {user['username']} 申请重置密码")
    return ok(msg="申请已提交，管理员审核通过后密码将重置为 123456")


@router.get("/reset-requests")
def list_reset_requests(user: dict = Depends(require_perm("user:edit"))):
    """管理员查看密码重置申请列表"""
    rows = query("""SELECT r.id, r.reason, r.status, r.create_time, r.handle_time,
                           u.username, u.real_name, h.real_name handler_name
                    FROM password_reset_request r
                    JOIN sys_user u ON r.user_id=u.id
                    LEFT JOIN sys_user h ON r.handler_id=h.id
                    ORDER BY FIELD(r.status,'pending','approved','rejected'), r.id DESC LIMIT 100""")
    pending = sum(1 for r in rows if r["status"] == "pending")
    return ok({"list": rows, "pending": pending})


@router.post("/reset-requests/{rid}/approve")
def approve_reset(rid: int, user: dict = Depends(require_perm("user:edit"))):
    """管理员通过申请：用户密码自动重置为 123456"""
    req = query_one("SELECT * FROM password_reset_request WHERE id=%s", (rid,))
    if not req:
        return fail("申请不存在")
    if req["status"] != "pending":
        return fail("该申请已处理")
    target = query_one("SELECT * FROM sys_user WHERE id=%s", (req["user_id"],))
    if not target:
        return fail("申请用户已不存在")
    execute("UPDATE sys_user SET password_hash=%s WHERE id=%s", (hash_password("123456"), target["id"]))
    execute("UPDATE password_reset_request SET status='approved', handler_id=%s, handle_time=NOW() WHERE id=%s",
            (user["id"], rid))
    add_log(None, user, "认证", "审批重置", f"通过 {target['username']} 的重置申请，密码已重置为 123456")
    return ok(msg=f"已通过，{target['username']} 的密码重置为 123456")


@router.post("/reset-requests/{rid}/reject")
def reject_reset(rid: int, user: dict = Depends(require_perm("user:edit"))):
    """管理员拒绝申请"""
    req = query_one("SELECT * FROM password_reset_request WHERE id=%s", (rid,))
    if not req:
        return fail("申请不存在")
    if req["status"] != "pending":
        return fail("该申请已处理")
    execute("UPDATE password_reset_request SET status='rejected', handler_id=%s, handle_time=NOW() WHERE id=%s",
            (user["id"], rid))
    add_log(None, user, "认证", "审批重置", f"拒绝了重置申请 id={rid}")
    return ok(msg="已拒绝")


@router.post("/change-password")
def change_password(body: ChangePwdBody, user: dict = Depends(get_current_user)):
    if not verify_password(body.old_password, user["password_hash"]):
        return fail("原密码错误")
    execute("UPDATE sys_user SET password_hash=%s WHERE id=%s", (hash_password(body.new_password), user["id"]))
    add_log(None, user, "认证", "修改密码", f"用户 {user['username']} 修改了密码")
    return ok(msg="密码修改成功")
