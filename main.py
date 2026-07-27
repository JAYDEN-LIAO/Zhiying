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
import os

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

    # 清理 socks 代理（httpx/openai 不支持 socks scheme）
    for _key in ("ALL_PROXY", "all_proxy"):
        if os.environ.pop(_key, None) is not None:
            logger.info("Unset %s (httpx incompatible)", _key)

    config = load_config()
    app.state.config = config
    app.state.db_session_factory = AsyncSessionLocal
    await init_db()

    # 启动时加载共享 embedder（模型仅 2B，占 ~4GB 显存），
    # Pipeline 和 Search 复用同一实例，避免重复加载
    logger.info("Loading shared embedder ...")
    from plugins.factory import load_plugin as _load_embedder
    app.state.embedder = await _load_embedder(config, "embedder")
    logger.info("Embedder loaded, GPU ready")

    # 预加载 captioner — 暂时关闭以节省显存，按需开启
    # GB10 128GB 统一内存：embedder(8B) ~16GB + captioner(8B) ~16GB = ~32GB
    # logger.info("Loading shared captioner ...")
    # from plugins.factory import load_plugin as _load_captioner
    # app.state.captioner = await _load_captioner(config, "captioner")
    # if app.state.captioner is not None:
    #     if hasattr(app.state.captioner, "preload"):
    #         await app.state.captioner.preload()
    #     logger.info("Captioner loaded, GPU ready")
    # else:
    #     logger.info("Captioner disabled (backend is null)")
    logger.info("Captioner preload: SKIPPED")
    app.state.captioner = None

    # 人脸识别器 — 搜索端点用（图片搜人脸）
    logger.info("Loading face recognizer ...")
    from plugins.factory import load_plugin as _load_face
    app.state.face_recognizer = await _load_face(config, "face")
    if app.state.face_recognizer is not None:
        logger.info("Face recognizer loaded")
    else:
        logger.info("Face recognizer disabled (backend is null)")

    # 物体检测器 — 不预加载，Pipeline execution 时按需加载（YOLO11s 加载 < 1s）
    # 一个 Pipeline 只加载一次，不存在重复实例化

    # SearchEngine 不在此处预初始化——embedder 按需加载，首次搜索时自动创建

    # 格式兼容服务 — 容器标准化 + 编码代理转码
    from services.format_service import FormatService
    app.state.format_service = FormatService(config, AsyncSessionLocal)
    logger.info("FormatService ready")

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
