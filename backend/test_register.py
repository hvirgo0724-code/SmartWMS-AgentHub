# -*- coding: utf-8 -*-
"""注册流程验证：身份证号 + 手机号 + 验证码"""
import requests

BASE = "http://127.0.0.1:8000/api/v1"
PASS, FAIL = 0, 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name} -> {detail}")


# 1. 手机号格式校验
r = requests.post(f"{BASE}/auth/register-code", json={"phone": "12345"}).json()
check("非法手机号被拒绝", r["code"] != 0, r)

# 2. 已绑定手机号被拒绝
r = requests.post(f"{BASE}/auth/register-code", json={"phone": "13800000002"}).json()
check("已注册手机号被拒绝", r["code"] != 0 and "已被注册" in r["msg"], r)

# 3. 新手机号获取验证码成功
phone = "13912345678"
r = requests.post(f"{BASE}/auth/register-code", json={"phone": phone}).json()
check("新手机号获取验证码成功", r["code"] == 0 and len(r["data"]["code"]) == 6, r)
code = r["data"]["code"]

# 4. 非法身份证号被拒绝（校验位错误）
r = requests.post(f"{BASE}/auth/register", json={
    "username": "regtest01", "password": "123456", "real_name": "注册测试",
    "id_card": "110101199003077513", "phone": phone, "code": code,
}).json()
check("校验位错误的身份证被拒绝", r["code"] != 0 and "校验位" in r["msg"], r)

# 5. 错误验证码被拒绝
r = requests.post(f"{BASE}/auth/register", json={
    "username": "regtest01", "password": "123456", "real_name": "注册测试",
    "id_card": "110101199003077512", "phone": phone, "code": "000000",
}).json()
check("错误验证码被拒绝", r["code"] != 0, r)

# 6. 正确信息注册成功
r = requests.post(f"{BASE}/auth/register", json={
    "username": "regtest01", "password": "123456", "real_name": "注册测试",
    "id_card": "110101199003077512", "phone": phone, "code": code,
}).json()
check("完整信息注册成功", r["code"] == 0, r)

# 7. 同手机号重复注册被拒绝（需重新获取验证码后测）
r = requests.post(f"{BASE}/auth/register-code", json={"phone": phone}).json()
if r["code"] == 0:
    r = requests.post(f"{BASE}/auth/register", json={
        "username": "regtest02", "password": "123456", "real_name": "重复测试",
        "id_card": "110101199003077512", "phone": phone, "code": r["data"]["code"],
    }).json()
    check("同手机号重复注册被拒绝", r["code"] != 0 and "已被注册" in r["msg"], r)

# 8. 新手机号 + 同身份证号被拒绝
r = requests.post(f"{BASE}/auth/register-code", json={"phone": "13912345679"}).json()
r = requests.post(f"{BASE}/auth/register", json={
    "username": "regtest02", "password": "123456", "real_name": "重复测试",
    "id_card": "110101199003077512", "phone": "13912345679", "code": r["data"]["code"],
}).json()
check("同身份证号重复注册被拒绝", r["code"] != 0 and "身份证号已注册" in r["msg"], r)

# 9. 新注册账号可登录
r = requests.post(f"{BASE}/auth/login", json={"username": "regtest01", "password": "123456"}).json()
check("新账号可正常登录", r["code"] == 0, r)

print(f"\n结果: {PASS} 通过 / {FAIL} 失败")
exit(1 if FAIL else 0)
