"""Top-level API router composition for backend endpoints."""

from fastapi import APIRouter

from app.api.routes import access, invitations_admin, system, webhooks

api_router = APIRouter()
api_router.include_router(system.router)
api_router.include_router(access.router)
api_router.include_router(invitations_admin.router)
api_router.include_router(webhooks.router)
