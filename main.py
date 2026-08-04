"""
main.py
═══════════════════════════════════════════════════════════
FastAPI 应用入口 — Cerno Video Analytics Core Engine

启动流程：
  1. lifespan → 加载配置 + init_db（创建扩展、触发器函数、表）
  2. 注册全局异常处理器（数据库/Pydantic/通用）
  3. 挂载 API 路由（/api/v1/...）
"""

import gzip
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
# 静默 uvicorn access log — GET/POST 请求行不打印
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
# 静默 ultralytics WARNING（运动补偿 "not enough matching points" 无害）
logging.getLogger("ultralytics").setLevel(logging.ERROR)
# 静默 bitsandbytes WARNING（8bit 量化每次 matmul 都刷 "bf16→fp16 cast"，无害纯噪音）
logging.getLogger("bitsandbytes").setLevel(logging.ERROR)
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

    # 物体检测器 — 共享单实例（模型懒加载，首次 detect 才载入 ~2GB）
    # 避免每个视频重载 YOLO；配合 core/gpu_lock 与 embedder 串行，防并发驱动故障
    logger.info("Loading shared object detector ...")
    from plugins.factory import load_plugin as _load_det
    app.state.detector = await _load_det(config, "detector")
    if app.state.detector is not None:
        logger.info("Object detector shared instance ready (model lazy)")
    else:
        logger.info("Object detector disabled (backend is null)")

    # SearchEngine 不在此处预初始化——embedder 按需加载，首次搜索时自动创建

    # 格式兼容服务 — 容器标准化 + 编码代理转码
    from services.format_service import FormatService
    app.state.format_service = FormatService(config, AsyncSessionLocal)
    logger.info("FormatService ready")

    # 存储管理器 — 删除时清盘 + 孤儿清扫（路径解析/引用追踪/卫生对账）
    from core.storage_manager import StorageManager
    app.state.storage_manager = StorageManager(config)
    logger.info("StorageManager ready")

    yield
    await engine.dispose()
    logger.info("Cerno engine shut down.")


# ──────────────────────────────────────────────────────────
# 仅 JSON 响应的 gzip 压缩中间件（v0.22, S0/A4）
# ──────────────────────────────────────────────────────────

class JSONGZipMiddleware:
    """只压缩 `application/json` 响应的 gzip 中间件。

    不能全局挂 `GZipMiddleware`：
      - `/videos/{id}/stream` 返回 206/Range 视频流 —— 压缩已压缩的 H.264 纯费 CPU，
        且破坏播放器 seek 语义（必须原样直通，零缓冲）；
      - `/detection/thumbnail`、`/face/thumbnail` 等 JPEG 已压缩，再压无收益。

    高熵 JSON（检测数据等）压缩比 >10×，一次红利。
    非 JSON 响应在 `http.response.start` 即直通转发，不做任何缓冲。
    """

    def __init__(self, app, minimum_size: int = 1024, compresslevel: int = 6):
        self.app = app
        self.minimum_size = minimum_size
        self.compresslevel = compresslevel

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        start_message = None       # 缓存的 response.start（JSON 压缩候选）
        body_buffer: list[bytes] = []
        compress = False

        async def send_wrapper(message):
            nonlocal start_message, body_buffer, compress
            if message["type"] == "http.response.start":
                headers = dict(message["headers"])
                content_type = headers.get(b"content-type", b"").decode("latin-1")
                has_encoding = any(k.lower() == b"content-encoding" for k, _ in message["headers"])
                compress = content_type.startswith("application/json") and not has_encoding
                if compress:
                    # 延迟转发：等 body 到齐后决定是否压缩（JSON 单块，成本可忽略）
                    start_message = message
                else:
                    await send(message)   # 视频流/JPEG/其他 → 原样直通
            elif message["type"] == "http.response.body":
                if not compress:
                    await send(message)
                    return
                body_buffer.append(message.get("body", b""))
                if message.get("more_body", False):
                    return
                body = b"".join(body_buffer)
                payload, content_encoding = body, None
                if len(body) >= self.minimum_size:
                    gz = gzip.compress(body, compresslevel=self.compresslevel)
                    if len(gz) < len(body):
                        payload, content_encoding = gz, "gzip"
                # 改写 content-length / content-encoding（重建 header 列表，避免遍历中删除索引漂移）
                start_message["headers"] = [
                    (k, v) for k, v in start_message["headers"]
                    if k.lower() not in (b"content-length", b"content-encoding")
                ]
                start_message["headers"].append((b"content-length", str(len(payload)).encode("latin-1")))
                if content_encoding:
                    start_message["headers"].append((b"content-encoding", b"gzip"))
                await send(start_message)
                await send({"type": "http.response.body", "body": payload, "more_body": False})
            else:
                await send(message)

        await self.app(scope, receive, send_wrapper)


# ──────────────────────────────────────────────────────────
# App
# ──────────────────────────────────────────────────────────

app = FastAPI(
    title="Cerno Video Analytics Core Engine",
    version="0.5",
    lifespan=lifespan,
)

app.add_middleware(JSONGZipMiddleware, minimum_size=1024)


@app.get("/health", tags=["system"])
async def health_check() -> JSONResponse:
    """轻量启动检查，供 Windows 启动脚本和 Electron 调用。

    除服务存活外，额外探测数据库连通性（SELECT 1，1s 超时），
    方便部署脚本判断"服务起来了、但数据库还没就绪"的情况。
    """
    import asyncio

    from sqlalchemy import text as sa_text

    database = "ok"
    try:
        async with asyncio.timeout(1.0):
            async with AsyncSessionLocal() as session:
                await session.execute(sa_text("SELECT 1"))
    except Exception:
        database = "unreachable"

    body = {"status": "ok", "service": "cerno", "database": database}
    code = 200 if database == "ok" else 503
    return JSONResponse(status_code=code, content=body)


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
