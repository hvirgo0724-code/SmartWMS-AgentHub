"""智能仓储管理系统 WMS - FastAPI 后端入口"""
from fastapi import FastAPI, Request, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
import os

from config import FRONTEND_DIR
from database import get_conn
from routers import auth, sysmgmt, basedata, inbound, outbound, inventory, analytics, system, cs, scan

app = FastAPI(title="智能仓储管理系统 WMS", version="2.0.0",
              description="前后端分离智能仓储管理系统：入库/出库/库存/盘点/智能决策全流程联动 + RAG 多 Agent 智能客服")


@app.on_event("startup")
def _startup_bootstrap():
    """增量建表 / 索引 / 权限 / 内置知识库；失败不阻塞主业务"""
    try:
        from agents.bootstrap import ensure_cs_schema
        info = ensure_cs_schema()
        print(f"[startup] 智能客服模块就绪: {info}")
    except Exception as e:
        print(f"[startup] 智能客服模块初始化失败（不影响主业务）: {e}")

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])

app.include_router(auth.router, prefix="/api/v1")
app.include_router(sysmgmt.router, prefix="/api/v1")
app.include_router(basedata.router, prefix="/api/v1")
app.include_router(inbound.router, prefix="/api/v1")
app.include_router(outbound.router, prefix="/api/v1")
app.include_router(inventory.router, prefix="/api/v1")
app.include_router(analytics.router, prefix="/api/v1")
app.include_router(system.router, prefix="/api/v1")
app.include_router(cs.router, prefix="/api/v1")
app.include_router(scan.router, prefix="/api/v1")


# 参数校验失败统一返回标准格式，避免前端显示 undefined
@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError):
    first = exc.errors()[0] if exc.errors() else {}
    loc = ".".join(str(x) for x in first.get("loc", [])[1:]) or "参数"
    return JSONResponse({"code": 422, "msg": f"参数错误：{loc} {first.get('msg', '格式不正确')}", "data": None})


# HTTP 异常（401/403/404 等）统一返回标准格式，前端可显示具体 msg
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse({"code": exc.status_code, "msg": str(exc.detail), "data": None},
                        status_code=exc.status_code)


@app.get("/api/v1/health")
def health():
    try:
        with get_conn() as conn:
            conn.cursor().execute("SELECT 1")
        from agents import llm, retriever
        try:
            kb = retriever.kb_stats()
        except Exception:
            kb = {"documents": 0, "chunks": 0}
        return {"code": 0, "msg": "ok", "data": {
            "db": "connected", "kb": kb, "llm": "enabled" if llm.is_enabled() else "fallback"
        }}
    except Exception as e:
        return {"code": 1, "msg": f"数据库连接失败: {e}", "data": None}


# ---------- 前端静态资源 ----------
class NoCacheStatic(StaticFiles):
    """静态资源禁用浏览器强缓存，确保前端更新即时生效"""
    def file_response(self, *args, **kwargs):
        resp = super().file_response(*args, **kwargs)
        resp.headers["Cache-Control"] = "no-cache"
        return resp


if os.path.isdir(FRONTEND_DIR):
    app.mount("/static", NoCacheStatic(directory=FRONTEND_DIR), name="static")

    @app.get("/")
    def index():
        resp = FileResponse(os.path.join(FRONTEND_DIR, "login.html"))
        resp.headers["Cache-Control"] = "no-cache"
        return resp

    @app.get("/app")
    def app_page():
        resp = FileResponse(os.path.join(FRONTEND_DIR, "app.html"))
        resp.headers["Cache-Control"] = "no-cache"
        return resp


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
