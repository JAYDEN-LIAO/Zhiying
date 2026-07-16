"""
main.py
═══════════════════════════════════════════════════════════
FastAPI 应用入口 — Cerno Video Analytics Core Engine

启动流程：
  1. lifespan → 加载配置 + init_db（创建扩展、触发器函数、表）
  2. 注册全局异常处理器（数据库/Pydantic/通用）
  3. 挂载 API 路由（/api/v1/...）
"""

import logging

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from core.db import engine, AsyncSessionLocal, init_db
from core.config_loader import load_config
from api.router import router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────
# Lifespan
# ──────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时初始化 DB，关闭时释放连接池。"""
    logger.info("Starting Cerno engine ...")
    config = load_config()
    app.state.config = config
    app.state.db_session_factory = AsyncSessionLocal
    await init_db()

    # 启动时加载共享 embedder（4GB 模型进显存），
    # Pipeline 和 Search 复用此实例，避免每视频重复加载
    # 不预加载任何 GPU 模型（embedder / caption 模型在需要时延迟加载）
    app.state.embedder = None
    logger.info("GPU models will be loaded on demand (embedder for search, "
                 "caption model for pipeline)")

    # 预热 SearchEngine（纯 CPU 对象，触发模块导入）
    from pipeline.search_engine import SearchEngine
    app.state._searcher = SearchEngine(AsyncSessionLocal, None)
    logger.info("SearchEngine pre-initialized")

    yield
    await engine.dispose()
    logger.info("Cerno engine shut down.")


# ──────────────────────────────────────────────────────────
# App
# ──────────────────────────────────────────────────────────

app = FastAPI(
    title="Cerno Video Analytics Core Engine",
    version="0.5",
    lifespan=lifespan,
)


# ──────────────────────────────────────────────────────────
# 全局异常处理器
# ──────────────────────────────────────────────────────────

@app.exception_handler(RequestValidationError)
async def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Pydantic 校验失败 → 422。"""
    return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.exception_handler(SQLAlchemyError)
async def handle_db_error(request: Request, exc: SQLAlchemyError) -> JSONResponse:
    """数据库连接超时 / 查询异常 → 500。"""
    logger.exception("Database error: %s", exc)
    return JSONResponse(status_code=500, content={"detail": "Internal database error"})


@app.exception_handler(Exception)
async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    """未预期异常兜底 → 500。"""
    logger.exception("Unexpected error: %s", exc)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


# ──────────────────────────────────────────────────────────
# 路由挂载
# ──────────────────────────────────────────────────────────

app.include_router(router)
