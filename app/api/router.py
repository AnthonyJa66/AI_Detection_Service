"""Top-level REST API router."""

from fastapi import APIRouter

from app.api import cameras, health


api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(cameras.router)
