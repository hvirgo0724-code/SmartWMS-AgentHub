"""系统管理-用户与角色权限（RBAC）"""
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from typing import Optional
from database import query, query_one, execute, execute_return_id, add_log
from security import hash_password
from deps import get_current_user, require_perm, ok, fail

router = APIRouter(tags=["系统管理"])


# ---------- 用户管理 ----------
class UserBody(BaseModel):
    username: str
    real_name: str = ""
    phone: str = ""
    email: str = ""
    password: str = "123456"
    status: int = 1
    role_ids: list[int] = []


@router.get("/users")
def list_users(page: int = 1, size: int = 10, keyword: str = "", user: dict = Depends(require_perm("user:view"))):
    where, params = "1=1", []
    if keyword:
        where += " AND (username LIKE %s OR real_name LIKE %s)"
        params += [f"%{keyword}%"] * 2
    total = query_one(f"SELECT COUNT(*) c FROM sys_user WHERE {where}", params)["c"]
    rows = query(
        f"""SELECT u.*, GROUP_CONCAT(r.role_name) role_names, GROUP_CONCAT(r.id) role_ids
            FROM sys_user u LEFT JOIN sys_user_role ur ON ur.user_id=u.id LEFT JOIN sys_role r ON r.id=ur.role_id
            WHERE {where} GROUP BY u.id ORDER BY u.id LIMIT %s OFFSET %s""",
        params + [size, (page - 1) * size])
    return ok({"total": total, "list": rows})


@router.post("/users")
def create_user(body: UserBody, user: dict = Depends(require_perm("user:add"))):
    if query_one("SELECT id FROM sys_user WHERE username=%s", (body.username,)):
        return fail("用户名已存在")
    with_user = {"id": 0, "username": user["username"], "ip": user.get("ip", "")}
    uid = execute_return_id(
        "INSERT INTO sys_user (username, password_hash, real_name, phone, email, status) VALUES (%s,%s,%s,%s,%s,%s)",
        (body.username, hash_password(body.password), body.real_name, body.phone, body.email, body.status))
    for rid in body.role_ids:
        execute("INSERT INTO sys_user_role (user_id, role_id) VALUES (%s,%s)", (uid, rid))
    add_log(None, with_user, "用户管理", "新增", f"创建用户 {body.username}")
    return ok({"id": uid}, "创建成功")


@router.put("/users/{uid}")
def update_user(uid: int, body: UserBody, user: dict = Depends(require_perm("user:edit"))):
    if not query_one("SELECT id FROM sys_user WHERE id=%s", (uid,)):
        return fail("用户不存在")
    execute("UPDATE sys_user SET username=%s, real_name=%s, phone=%s, email=%s, status=%s WHERE id=%s",
            (body.username, body.real_name, body.phone, body.email, body.status, uid))
    execute("DELETE FROM sys_user_role WHERE user_id=%s", (uid,))
    for rid in body.role_ids:
        execute("INSERT IGNORE INTO sys_user_role (user_id, role_id) VALUES (%s,%s)", (uid, rid))
    add_log(None, user, "用户管理", "修改", f"更新用户 {body.username}")
    return ok(msg="更新成功")


@router.delete("/users/{uid}")
def delete_user(uid: int, user: dict = Depends(require_perm("user:delete"))):
    if uid == user["id"]:
        return fail("不能删除当前登录用户")
    execute("DELETE FROM sys_user WHERE id=%s", (uid,))
    execute("DELETE FROM sys_user_role WHERE user_id=%s", (uid,))
    add_log(None, user, "用户管理", "删除", f"删除用户 id={uid}")
    return ok(msg="删除成功")


@router.post("/users/{uid}/reset-password")
def reset_password(uid: int, user: dict = Depends(require_perm("user:edit"))):
    execute("UPDATE sys_user SET password_hash=%s WHERE id=%s", (hash_password("123456"), uid))
    add_log(None, user, "用户管理", "重置密码", f"重置用户 id={uid} 密码为默认")
    return ok(msg="密码已重置为 123456")


# ---------- 角色管理 ----------
class RoleBody(BaseModel):
    role_name: str
    role_code: str
    description: str = ""
    perm_ids: list[int] = []


@router.get("/roles")
def list_roles(user: dict = Depends(require_perm("role:view"))):
    roles = query("SELECT * FROM sys_role ORDER BY id")
    for r in roles:
        r["perm_ids"] = [p["perm_id"] for p in query("SELECT perm_id FROM sys_role_permission WHERE role_id=%s", (r["id"],))]
        r["user_count"] = query_one("SELECT COUNT(*) c FROM sys_user_role WHERE role_id=%s", (r["id"],))["c"]
    return ok(roles)


@router.post("/roles")
def create_role(body: RoleBody, user: dict = Depends(require_perm("role:add"))):
    if query_one("SELECT id FROM sys_role WHERE role_code=%s", (body.role_code,)):
        return fail("角色编码已存在")
    rid = execute_return_id("INSERT INTO sys_role (role_name, role_code, description) VALUES (%s,%s,%s)",
                  (body.role_name, body.role_code, body.description))
    for pid in body.perm_ids:
        execute("INSERT INTO sys_role_permission (role_id, perm_id) VALUES (%s,%s)", (rid, pid))
    add_log(None, user, "角色管理", "新增", f"创建角色 {body.role_name}")
    return ok({"id": rid}, "创建成功")


@router.put("/roles/{rid}")
def update_role(rid: int, body: RoleBody, user: dict = Depends(require_perm("role:edit"))):
    execute("UPDATE sys_role SET role_name=%s, role_code=%s, description=%s WHERE id=%s",
            (body.role_name, body.role_code, body.description, rid))
    execute("DELETE FROM sys_role_permission WHERE role_id=%s", (rid,))
    for pid in body.perm_ids:
        execute("INSERT INTO sys_role_permission (role_id, perm_id) VALUES (%s,%s)", (rid, pid))
    add_log(None, user, "角色管理", "修改", f"更新角色 {body.role_name}")
    return ok(msg="更新成功")


@router.delete("/roles/{rid}")
def delete_role(rid: int, user: dict = Depends(require_perm("role:delete"))):
    if query_one("SELECT 1 FROM sys_user_role WHERE role_id=%s LIMIT 1", (rid,)):
        return fail("该角色已分配用户，请先解除绑定")
    execute("DELETE FROM sys_role WHERE id=%s", (rid,))
    execute("DELETE FROM sys_role_permission WHERE role_id=%s", (rid,))
    add_log(None, user, "角色管理", "删除", f"删除角色 id={rid}")
    return ok(msg="删除成功")


@router.get("/permissions")
def list_permissions(user: dict = Depends(get_current_user)):
    return ok(query("SELECT * FROM sys_permission ORDER BY id"))
