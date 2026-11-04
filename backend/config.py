"""全局配置"""
import os

DB_CONFIG = {
    "host": os.getenv("WMS_DB_HOST", "localhost"),
    "port": int(os.getenv("WMS_DB_PORT", 3306)),
    "user": os.getenv("WMS_DB_USER", "root"),
    "password": os.getenv("WMS_DB_PASSWORD", "123456"),
    "database": os.getenv("WMS_DB_NAME", "warehouse_management_system01"),
    "charset": "utf8mb4",
}

JWT_SECRET = os.getenv("WMS_JWT_SECRET", "wms-secret-key-2026-smart-warehouse")
JWT_EXPIRE_HOURS = 24

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR = os.path.join(os.path.dirname(BASE_DIR), "frontend")

# ---------- 智能客服 / RAG ----------
# 大模型为可选项：配置 OpenAI 兼容接口后启用生成式回答，未配置时自动降级为本地检索式回答
LLM_BASE = os.getenv("WMS_LLM_BASE", "").rstrip("/")          # 例: https://api.openai.com/v1
LLM_KEY = os.getenv("WMS_LLM_KEY", "")
LLM_MODEL = os.getenv("WMS_LLM_MODEL", "gpt-4o-mini")
LLM_TIMEOUT = int(os.getenv("WMS_LLM_TIMEOUT", "30"))

# 供应商 / 商家开放接口密钥（生产环境请通过环境变量覆盖）
PARTNER_API_KEY = os.getenv("WMS_PARTNER_KEY", "wms-partner-demo-key")

# 检索参数（字符级 BM25 + 语义哈希向量混合召回）
KB_CHUNK_SIZE = int(os.getenv("WMS_KB_CHUNK_SIZE", "320"))
KB_CHUNK_OVERLAP = int(os.getenv("WMS_KB_OVERLAP", "60"))
KB_TOP_K = int(os.getenv("WMS_KB_TOP_K", "6"))
KB_MIN_SCORE = float(os.getenv("WMS_KB_MIN_SCORE", "0.18"))
