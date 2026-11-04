"""请求依赖：JWT 认证、权限校验、通用响应"""
from fastapi import Depends, Request, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from database import query, query_one
from security import decode_token

bearer = HTTPBearer(auto_error=False)


def ok(data=None, msg="success"):
    return {"code": 0, "msg": msg, "data": data}


def fail(msg="error", code=1):
    return {"code": code, "msg": msg, "data": None}


def get_current_user(request: Request, cred: HTTPAuthorizationCredentials = Depends(bearer)) -> dict:
    token = cred.credentials if cred else request.headers.get("token")
    if not token:
        raise HTTPException(401, "未登录")
    payload = decode_token(token)
    if not payload:
        raise HTTPException(401, "登录已过期，请重新登录")
    user = query_one("SELECT * FROM sys_user WHERE id=%s", (payload.get("uid"),))
    if not user or user.get("status") != 1:
        raise HTTPException(401, "用户不可用")
    user["ip"] = request.client.host if request.client else ""
    # 权限实时读取数据库，避免角色/权限调整后旧 Token 权限不生效
    try:
        role_rows = query("""SELECT r.role_code FROM sys_role r
                             JOIN sys_user_role ur ON ur.role_id=r.id WHERE ur.user_id=%s""", (user["id"],))
        perm_rows = query("""SELECT DISTINCT p.perm_code FROM sys_permission p
                             JOIN sys_role_permission rp ON rp.perm_id=p.id
                             JOIN sys_user_role ur ON ur.role_id=rp.role_id WHERE ur.user_id=%s""", (user["id"],))
        role_codes = [r["role_code"] for r in role_rows]
        perm_codes = [p["perm_code"] for p in perm_rows]
        if "admin" in role_codes:
            perm_codes = ["*"]
        user["perms"] = perm_codes
        user["roles"] = role_codes
    except Exception:
        user["perms"] = payload.get("perms", [])
        user["roles"] = payload.get("roles", [])
    return user


def require_perm(code: str):
    """权限校验依赖工厂：require_perm('product:add')"""
    def checker(user: dict = Depends(get_current_user)):
        if "*" in user.get("perms", []):
            return user
        if code not in user.get("perms", []):
            raise HTTPException(403, f"无权限: {code}")
        return user
    return checker
