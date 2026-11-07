"""API v1 — combines all endpoint routers."""
from fastapi import APIRouter
from app.api.v1.endpoints import auth, config, videos, packages, orders, ads, misc, admin, admin_auth, admin_payment_methods, admin_config, admin_manage, admin_ops

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(auth.router)
api_router.include_router(config.router)
api_router.include_router(videos.router)
api_router.include_router(packages.router)
api_router.include_router(orders.router)
api_router.include_router(ads.router)
api_router.include_router(misc.router)
api_router.include_router(admin_auth.router)
api_router.include_router(admin.router)
api_router.include_router(admin_payment_methods.router)
api_router.include_router(admin_config.router)
api_router.include_router(admin_manage.router)
api_router.include_router(admin_ops.router)
