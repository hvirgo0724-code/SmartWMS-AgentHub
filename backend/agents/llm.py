"""OpenAI 兼容大模型接入：支持环境变量或系统参数动态配置，失败自动降级"""
import json
import os
import time
import urllib.request
import urllib.error

from config import LLM_BASE, LLM_KEY, LLM_MODEL, LLM_TIMEOUT
from database import query, execute

_CACHE = {"ts": 0.0, "cfg": None}
_TTL = 8
_LAST_ERROR = ""


def _db_config():
    try:
        rows = query("""SELECT config_key, config_value FROM sys_config
                        WHERE config_key IN ('llm_base','llm_key','llm_model','llm_timeout')""")
        return {r["config_key"]: (r["config_value"] or "").strip() for r in rows}
    except Exception:
        return {}


def _config():
    now = time.time()
    if _CACHE["cfg"] is not None and now - _CACHE["ts"] < _TTL:
        return _CACHE["cfg"]
    db = _db_config()
    base = os.getenv("WMS_LLM_BASE", "").strip() or db.get("llm_base", "") or LLM_BASE
    key = os.getenv("WMS_LLM_KEY", "").strip() or db.get("llm_key", "") or LLM_KEY
    model = os.getenv("WMS_LLM_MODEL", "").strip() or db.get("llm_model", "") or LLM_MODEL
    try:
        timeout = int(os.getenv("WMS_LLM_TIMEOUT", "") or db.get("llm_timeout") or LLM_TIMEOUT)
    except ValueError:
        timeout = LLM_TIMEOUT
    cfg = {"base": base.rstrip("/"), "key": key, "model": model, "timeout": timeout}
    _CACHE.update(ts=now, cfg=cfg)
    return cfg


def reload():
    _CACHE["ts"] = 0.0
    _CACHE["cfg"] = None


def is_enabled():
    cfg = _config()
    return bool(cfg["base"] and cfg["key"])


def public_config():
    cfg = _config()
    key = cfg["key"]
    masked = ""
    if key:
        masked = f"{key[:5]}****{key[-4:]}" if len(key) > 10 else "****"
    return {"base": cfg["base"], "model": cfg["model"], "timeout": cfg["timeout"],
            "key_masked": masked, "enabled": bool(cfg["base"] and key)}


def last_error():
    return _LAST_ERROR


def _set_config(key, value):
    execute("""INSERT INTO sys_config (config_key, config_value, description)
               VALUES (%s,%s,'AI 大模型配置')
               ON DUPLICATE KEY UPDATE config_value=VALUES(config_value)""", (key, value))


def update_config(base, key, model, timeout):
    """保存大模型配置；key 为空表示保留原密钥"""
    global _LAST_ERROR
    base = (base or "").strip().rstrip("/")
    model = (model or "").strip()
    if base:
        _set_config("llm_base", base)
    if model:
        _set_config("llm_model", model)
    try:
        _set_config("llm_timeout", str(int(timeout)))
    except (TypeError, ValueError):
        pass
    if key and key.strip():
        _set_config("llm_key", key.strip())
    reload()
    _LAST_ERROR = ""
    return public_config()


def chat(system: str, messages: list, temperature: float = 0.2, max_tokens: int = 900):
    """返回模型文本；不可用/异常时返回 None"""
    global _LAST_ERROR
    cfg = _config()
    if not (cfg["base"] and cfg["key"]):
        _LAST_ERROR = "未配置大模型 Base URL 或 API Key"
        return None
    url = cfg["base"] if cfg["base"].endswith("/chat/completions") else f"{cfg['base']}/chat/completions"
    payload = {
        "model": cfg["model"],
        "messages": [{"role": "system", "content": system}] + messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {cfg['key']}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=cfg["timeout"]) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        content = (data.get("choices") or [{}])[0].get("message", {}).get("content", "").strip()
        if content:
            _LAST_ERROR = ""
            return content
        _LAST_ERROR = "模型返回内容为空"
        return None
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8")[:200]
        except Exception:
            body = ""
        _LAST_ERROR = f"HTTP {e.code}: {body}"
        print(f"[cs][llm] 调用失败，降级为本地检索回答: {_LAST_ERROR}")
        return None
    except (urllib.error.URLError, TimeoutError, ValueError, KeyError) as e:
        _LAST_ERROR = str(e)
        print(f"[cs][llm] 调用失败，降级为本地检索回答: {e}")
        return None
