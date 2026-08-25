"""
api/router.py
═══════════════════════════════════════════════════════════
路由总装入口 — 组合所有子路由模块并挂载到 /api/v1 前缀。
"""

from fastapi import APIRouter

from api.video_routes import router as video_router
from api.search_routes import router as search_router
from api.settings_routes import router as settings_router
from api.detection_routes import router as detection_router
from api.export_routes import router as export_router
from api.face_routes import router as face_router
from api.plate_routes import router as plate_router
from api.ocr_routes import router as ocr_router
from api.maintenance_routes import router as maintenance_router
from api.groups_routes import router as groups_router
from api.tasks_routes import router as tasks_router
from api.subjects_routes import router as subjects_router

router = APIRouter(prefix="/api/v1")

router.include_router(video_router)
router.include_router(search_router)
router.include_router(settings_router)
router.include_router(detection_router, prefix="/videos")
router.include_router(export_router, prefix="/videos")
router.include_router(face_router, prefix="/videos")
router.include_router(plate_router, prefix="/videos")
router.include_router(ocr_router, prefix="/videos")
router.include_router(maintenance_router)
router.include_router(groups_router)
router.include_router(tasks_router)
router.include_router(subjects_router)
