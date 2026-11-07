"""
Video Store — FastAPI Backend
Runs FastAPI (API) + Telegram Bot (background asyncio task) on the same process.
This keeps Render Free tier usage within the 750 hr/month limit.
"""
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError

from app.core.config import settings, validate_runtime_config
from app.core.rate_limit import rate_limit_middleware
from app.db.firebase import init_firebase
from app.api.v1.router import api_router

logging.basicConfig(
    level=logging.DEBUG if settings.APP_DEBUG else logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

# The Monetag postback carries a secret in the query string → never log it.
from app.core.log_redact import RedactSecretsFilter  # noqa: E402
for _name in ("uvicorn.access", "uvicorn.error", "uvicorn", ""):
    logging.getLogger(_name).addFilter(RedactSecretsFilter())
for _h in logging.getLogger().handlers:
    _h.addFilter(RedactSecretsFilter())


# ─── Lifespan ─────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info(f"Starting Video Store Backend [{settings.APP_ENV}]")
    problems = validate_runtime_config()
    for p in problems:
        logger.warning(f"Config: {p}")
    if problems and settings.is_production:
        raise RuntimeError("Invalid production configuration: " + "; ".join(problems))
    init_firebase()
    from app.core import auto_secrets
    from app.db.firebase import get_db
    await auto_secrets.load_or_create(get_db())

    # Start Telegram Bot in background (same process, saves Render hours)
    bot_task = None
    try:
        from app.bot.main import start_bot
        bot_task = asyncio.create_task(start_bot())
        logger.info("Telegram Bot started ✓")
    except Exception as e:
        logger.warning(f"Bot not started (optional): {e}")

    yield

    # Shutdown
    if bot_task:
        bot_task.cancel()
        try:
            await bot_task
        except asyncio.CancelledError:
            pass
    logger.info("Backend stopped")


# ─── App ──────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="Video Store API",
    version="1.0.0",
    description="Telegram Mini App Video Store — Backend API",
    docs_url="/docs" if not settings.is_production else None,
    redoc_url="/redoc" if not settings.is_production else None,
    lifespan=lifespan,
)

# Rate limiting is registered BEFORE CORS: in Starlette the last-added
# middleware is outermost, so CORS wraps it and 429s still get CORS headers.
app.middleware("http")(rate_limit_middleware)

# ─── CORS ─────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_credentials="*" not in settings.allowed_origins_list,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)

# ─── Routers ──────────────────────────────────────────────────────────────────
app.include_router(api_router)


# ─── Error handlers ───────────────────────────────────────────────────────────
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    # Only plain, serialisable fields: pydantic v2 puts the raw exception object
    # in `ctx` (not JSON-serialisable → would turn a 422 into a 500) and echoes
    # the submitted value in `input` (never send that back).
    errors = [
        {"loc": [str(x) for x in e.get("loc", ())], "msg": str(e.get("msg", "")), "type": str(e.get("type", ""))}
        for e in exc.errors()
    ]
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": "Invalid request data", "errors": errors},
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Internal server error"},
    )


# ─── Health check ─────────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    return {"status": "ok", "env": settings.APP_ENV}


@app.get("/")
async def root():
    return {"app": "Video Store API", "version": "1.0.0"}
