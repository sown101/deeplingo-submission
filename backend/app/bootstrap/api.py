"""HTTP composition root: builds the FastAPI application."""
import logging
import time
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.platform.body_limit import BodySizeLimitMiddleware
from app.platform.config import settings
from app.platform.logging import setup_logging
from app.platform.persistence import request_read_cache

logger = logging.getLogger(__name__)


# CORS Middleware — browser (Web) boundary.
#
# The Web client authenticates with "Authorization: Bearer" only; no cookies
# are involved, so credentialed CORS is neither needed nor enabled. Origins
# are explicit and configuration-driven (BACKEND_CORS_ORIGINS, comma
# separated). When unset, a narrow local-development default keeps the
# Vite dev server workflow working; wildcard origins are never a default.
def cors_middleware_kwargs(origin_setting: str) -> dict:
    configured = [
        origin.strip()
        for origin in origin_setting.split(",")
        if origin.strip()
    ]
    return {
        "allow_origins": configured or ["http://localhost:5173", "http://127.0.0.1:5173"],
        "allow_credentials": False,
        "allow_methods": ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        "allow_headers": ["Accept", "Content-Type", "Authorization"],
    }


def v3_routers() -> list[tuple[APIRouter, str]]:
    """Mounted V3 routers in registration order (order matters for path matching)."""
    from app.modules.content.api.languages import router as content_languages_router
    from app.modules.learner.api.routes import router as learner_router
    from app.modules.content.api.library import router as v3_library_router
    from app.modules.content.api.playback import router as v3_video_playback_router
    from app.modules.learning.api.agent_memory import router as v3_agent_memory_router
    from app.modules.learning.api.study_requests import router as v3_study_requests_router
    from app.modules.learning.api.speaking import router as v3_speaking_router
    from app.modules.learning.api.practice_log import router as v3_practice_log_router
    from app.modules.learning.api.region_questions import router as v3_region_questions_router
    from app.modules.learning.api.region_result import router as v3_region_result_router
    from app.modules.learning.api.study_plan import router as v3_study_plan_router
    from app.modules.learning.api.realtime import router as v3_realtime_router
    from app.modules.activity.api.routes import router as activity_router
    from app.modules.practice.api.routes import router as practice_router
    from app.modules.progress.api.routes import router as progress_router

    return [
        (content_languages_router, "v3 Content"),
        (learner_router, "v3 Learner Model"),
        (v3_library_router, "v3 Learner Library"),
        (v3_video_playback_router, "v3 Video Playback"),
        (v3_speaking_router, "v3 Speaking Practice"),
        (v3_agent_memory_router, "v3 Agent Memory"),
        (v3_study_requests_router, "v3 Agent Study Requests"),
        (v3_practice_log_router, "v3 Practice Log"),
        (v3_region_questions_router, "v3 Region Questions"),
        (v3_region_result_router, "v3 Region Result"),
        (v3_study_plan_router, "v3 Study Plan"),
        (v3_realtime_router, "v3 Realtime Companion"),
        (activity_router, "v3 Activity"),
        (practice_router, "v3 Practice"),
        (progress_router, "v3 Progress"),
    ]


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("=" * 50)
    logger.info(f"🚀 Starting {settings.PROJECT_NAME}")
    logger.info(f"📍 Environment: {settings.ENVIRONMENT}")
    logger.info(f"🌐 API Docs: http://localhost:{settings.PORT}/docs")
    logger.info("=" * 50)
    yield
    logger.info("Shutting down...")


def create_app() -> FastAPI:
    setup_logging()
    app = FastAPI(
        title=settings.PROJECT_NAME,
        version="1.0.0",
        description="API học tiếng Anh qua YouTube với AI",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )
    # Innermost of the user middleware: oversized bodies are refused before any route parses
    # them, and the 413 still passes through CORS so browsers can read it.
    app.add_middleware(BodySizeLimitMiddleware)
    app.add_middleware(CORSMiddleware, **cors_middleware_kwargs(settings.BACKEND_CORS_ORIGINS))

    @app.middleware("http")
    async def log_request_lifecycle(request: Request, call_next):
        started = time.perf_counter()
        logger.info("HTTP start %s %s", request.method, request.url.path)
        try:
            # Shared-content reads are memoized for this request only (app.platform.persistence).
            with request_read_cache():
                response = await call_next(request)
        except Exception:
            elapsed_ms = (time.perf_counter() - started) * 1000
            logger.exception(
                "HTTP error %s %s after %.1fms",
                request.method,
                request.url.path,
                elapsed_ms,
            )
            raise
        elapsed_ms = (time.perf_counter() - started) * 1000
        logger.info(
            "HTTP end %s %s -> %s in %.1fms",
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
        )
        return response

    @app.get("/")
    async def root():
        return {
            "status": "Running",
            "environment": settings.ENVIRONMENT,
            "message": "DeepLingo API is alive! 🚀",
            "version": "1.0.0"
        }

    @app.get("/health")
    def health_check():
        """Kiểm tra tình trạng các services"""
        from app.platform.supabase import probe_database

        connected = probe_database()
        return JSONResponse({
            "status": "healthy" if connected else "unhealthy",
            "services": {
                "supabase": "connected" if connected else "disconnected",
            },
            "environment": settings.ENVIRONMENT
        }, status_code=200 if connected else 503)

    for router, tag in v3_routers():
        app.include_router(router, prefix=f"{settings.API_V1_STR}/v3", tags=[tag])

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        # Details go to server logs only; exception text can carry table names, paths
        # or provider bodies, so no environment returns it to callers.
        # The message names the type only; the traceback goes through the SEC-07 safe rendering.
        logger.error("Unhandled error %s", type(exc).__name__, exc_info=exc)

        return JSONResponse(
            status_code=500,
            content={"error": "InternalServerError", "message": "Lỗi hệ thống"},
        )

    return app
