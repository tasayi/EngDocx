"""EngDoc FastAPI Application Entrypoint."""

from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from engdoc.api.routes_projects import router as projects_router
from engdoc.api.routes_system import router as system_router
from engdoc.core.config import settings
from engdoc.project.session import SessionManager


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    # Cleanup any active temporary project session workspaces
    SessionManager.close_all()


def create_app() -> FastAPI:
    """Creates and configures the FastAPI application instance."""
    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.VERSION,
        description="Engineering Document Authoring and Publishing System",
        lifespan=lifespan,
    )

    # CORS configuration for local-first desktop usage
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # API Routers
    app.include_router(system_router, prefix=settings.API_PREFIX)
    app.include_router(projects_router, prefix=settings.API_PREFIX)

    # Mount frontend static directory if present
    if settings.FRONTEND_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=str(settings.FRONTEND_DIR)), name="static")

        @app.get("/", include_in_schema=False)
        async def serve_index() -> FileResponse:
            index_path = settings.FRONTEND_DIR / "index.html"
            if index_path.exists():
                return FileResponse(index_path)
            return FileResponse(settings.FRONTEND_DIR / "index.html")

    return app

app = create_app()

def main() -> None:
    """CLI runner to launch the EngDoc application server."""
    print(f"Starting {settings.APP_NAME} v{settings.VERSION} on http://{settings.HOST}:{settings.PORT}")
    uvicorn.run(
        "engdoc.api.app:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
        log_level="info",
    )

if __name__ == "__main__":
    main()
