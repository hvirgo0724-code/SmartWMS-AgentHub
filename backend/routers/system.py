"""系统管理：系统参数配置/操作日志/AI 大模型配置"""
import time
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from database import query, query_one, execute, add_log
from deps import get_current_user, require_perm, ok, fail
from agents import llm

router = APIRouter(tags=["系统管理"])


class LlmConfigBody(BaseModel):
    base: str = ""
    key: str = ""
    model: str = ""
    timeout: int = 30


@router.get("/configs/llm")
def get_llm_config(user: dict = Depends(require_perm("system:config"))):
    """查看大模型配置（密钥脱敏）"""
    return ok(llm.public_config())


@router.put("/configs/llm")
def update_llm_config(body: LlmConfigBody, user: dict = Depends(require_perm("system:config"))):
    base = (body.base or "").strip()
    if base and not base.startswith(("http://", "https://")):
        return fail("Base URL 必须以 http:// 或 https:// 开头")
    cfg = llm.update_config(base, body.key, body.model, body.timeout)
    add_log(None, user, "系统管理", "配置大模型",
            f"base={cfg['base']} model={cfg['model']} key={cfg['key_masked']}")
    return ok(cfg, "大模型配置已保存")


@router.post("/configs/llm/test")
def test_llm(user: dict = Depends(require_perm("system:config"))):
    """连通性测试：让模型回复固定文本"""
    t0 = time.time()
    answer = llm.chat("你是连通性测试助手，只回复用户要求的内容。",
                      [{"role": "user", "content": "请只回复：连接成功"}], max_tokens=32)
    if not answer:
        return fail(f"连接失败：{llm.last_error()}")
    return ok({"answer": answer, "latency_ms": int((time.time() - t0) * 1000)}, "大模型连接成功")


@router.get("/configs")
def list_configs(user: dict = Depends(require_perm("system:config"))):
    # 大模型配置由专用接口管理并做密钥脱敏，避免在通用参数列表中泄露
    return ok(query("""SELECT * FROM sys_config WHERE config_key NOT LIKE %s
                       ORDER BY id""", ("llm_%",)))


@router.put("/configs/{cid}")
def update_config(cid: int, body: dict, user: dict = Depends(require_perm("system:config"))):
    execute("UPDATE sys_config SET config_value=%s WHERE id=%s", (body.get("config_value", ""), cid))
    add_log(None, user, "系统管理", "修改参数", f"参数 id={cid} 改为 {body.get('config_value')}")
    return ok(msg="更新成功")


@router.get("/logs")
def list_logs(module: str = "", keyword: str = "", page: int = 1, size: int = 20,
              user: dict = Depends(require_perm("log:view"))):
    where, params = "1=1", []
    if module:
        where += " AND module=%s"
        params.append(module)
    if keyword:
        where += " AND (username LIKE %s OR detail LIKE %s)"
        params += [f"%{keyword}%"] * 2
    total = query_one(f"SELECT COUNT(*) c FROM sys_log WHERE {where}", params)["c"]
    rows = query(f"SELECT * FROM sys_log WHERE {where} ORDER BY id DESC LIMIT %s OFFSET %s",
                 params + [size, (page - 1) * size])
    return ok({"total": total, "list": rows})
