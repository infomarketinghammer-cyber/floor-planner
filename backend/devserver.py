"""Dev entry point run by `watchfiles devserver.run app` (see scripts/dev-backend.mjs)."""

import uvicorn


def run() -> None:
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000)
