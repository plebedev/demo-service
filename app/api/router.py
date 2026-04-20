from fastapi import APIRouter

from app.api.routes import system, webhooks

api_router = APIRouter()
api_router.include_router(system.router)
api_router.include_router(webhooks.router)
