"""
api/router.py
═══════════════════════════════════════════════════════════
路由总装入口 — 组合所有子路由模块并导出。

当前阶段将所有路由集中在 api/routes.py 中，
此文件作为总装入口供 main.py 导入。
"""

from api.routes import router

__all__ = ["router"]
