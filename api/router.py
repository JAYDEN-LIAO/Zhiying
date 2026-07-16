"""
api/router.py
═══════════════════════════════════════════════════════════
路由总装入口 — 组合所有子路由模块并挂载到 /api/v1 前缀。
"""

from fastapi import APIRouter

from api.video_routes import router as video_router
from api.search_routes import router as search_router
from api.settings_routes import router as settings_router

router = APIRouter(prefix="/api/v1")

router.include_router(video_router)
router.include_router(search_router)
router.include_router(settings_router)
