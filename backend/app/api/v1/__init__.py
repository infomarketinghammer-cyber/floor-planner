from fastapi import APIRouter, Depends

from app.api.v1 import (
    admin,
    auth,
    collab,
    cost,
    dashboards,
    exports,
    feedback,
    files,
    guest,
    history,
    materials,
    projects,
    public,
    quotes,
    rooms,
    scenarios,
    teams,
    tiles,
    users,
)
from app.core.activity import track_action

# Every route records what it does, for the project history and activity log.
api_router = APIRouter(prefix="/api/v1", dependencies=[Depends(track_action)])
api_router.include_router(auth.router)
api_router.include_router(history.router)  # before projects: /projects/import
api_router.include_router(projects.router)
api_router.include_router(files.router)
api_router.include_router(rooms.router)
api_router.include_router(materials.router)
api_router.include_router(cost.router)
api_router.include_router(exports.router)
api_router.include_router(feedback.router)
api_router.include_router(scenarios.router)
api_router.include_router(quotes.router)
api_router.include_router(collab.router)
api_router.include_router(dashboards.router)
api_router.include_router(teams.router)
api_router.include_router(tiles.router)
api_router.include_router(users.router)
api_router.include_router(admin.router)
api_router.include_router(public.router)
api_router.include_router(guest.router)
