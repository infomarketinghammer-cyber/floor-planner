from fastapi import APIRouter

from app.api.v1 import (
    admin,
    auth,
    cost,
    exports,
    feedback,
    files,
    guest,
    materials,
    projects,
    public,
    quotes,
    rooms,
    scenarios,
    tiles,
    users,
)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(projects.router)
api_router.include_router(files.router)
api_router.include_router(rooms.router)
api_router.include_router(materials.router)
api_router.include_router(cost.router)
api_router.include_router(exports.router)
api_router.include_router(feedback.router)
api_router.include_router(scenarios.router)
api_router.include_router(quotes.router)
api_router.include_router(tiles.router)
api_router.include_router(users.router)
api_router.include_router(admin.router)
api_router.include_router(public.router)
api_router.include_router(guest.router)
