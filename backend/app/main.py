from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from pymongo.errors import ConnectionFailure
from app.utils.sessions import require_session, allowed_origins
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from starlette.concurrency import run_in_threadpool
import time

# ACC chatbot API routes
from app.api.routes.chat import router as chat_router
from app.api.routes.cdr import router as cdr_router
from app.api.routes.relationship import router as relationship_router
from app.api.routes.statements import router as statements_router
from app.api.routes.conversations import router as conversations_router
from app.api.routes.folders import router as folders_router

# Authentication route from the frontend/backend integration
from app.routes.auth import router as auth_router
from app.api.routes.activity import router as activity_router
from app.api.routes.sources import router as sources_router
from app.ocr import config as ocr_config

ocr_config.initialize_config()
from app.api.routes.ocr_documents import router as ocr_documents_router
from app.api.routes.cims import router as cims_router


@asynccontextmanager
async def lifespan(app):
    ocr_config.validate_runtime()
    from acc_statements.index import embed, close_client
    started = time.monotonic()
    print("Preparing document search: loading and warming the embedding model...", flush=True)
    await run_in_threadpool(embed, ["Investigation document search warm-up"])
    print(f"Document search ready in {time.monotonic() - started:.1f}s. You can now submit questions.", flush=True)
    try:
        yield
    finally:
        close_client()


app = FastAPI(
    lifespan=lifespan,
    title="ACC Investigation Support System",
    description="Backend API for the ACC investigation support chatbot",
    version="1.0.0",
)

# Allow requests from the frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    return {"message": "ACC Investigation Chatbot API is running", "ocr_engine": ocr_config.OCR_ENGINE, "ocr_model": ocr_config.OCR_MODEL_ID}


# Register all routers
app.include_router(chat_router, dependencies=[Depends(require_session)])
app.include_router(cdr_router, dependencies=[Depends(require_session)])
app.include_router(relationship_router, dependencies=[Depends(require_session)])
app.include_router(auth_router)
app.include_router(cims_router)
app.include_router(statements_router, dependencies=[Depends(require_session)])
app.include_router(conversations_router, dependencies=[Depends(require_session)])
app.include_router(folders_router, dependencies=[Depends(require_session)])
app.include_router(activity_router, dependencies=[Depends(require_session)])
app.include_router(sources_router, dependencies=[Depends(require_session)])
app.include_router(ocr_documents_router, dependencies=[Depends(require_session)])


@app.exception_handler(ConnectionFailure)
async def database_unavailable(request: Request, exc: ConnectionFailure):
    return JSONResponse(status_code=503, content={"detail": "The database is unavailable. Please try again later."})


@app.middleware("http")
async def private_api_responses(request: Request, call_next):
    if request.url.path == "/api/cims/sync":
        content_length = request.headers.get("content-length")
        if content_length and content_length.isdigit() and int(content_length) > 1_048_576:
            response = JSONResponse(status_code=413, content={"detail": "Request body exceeds the 1 MiB limit."})
            response.headers["Cache-Control"] = "no-store"
            response.headers["X-Content-Type-Options"] = "nosniff"
            return response
    response = await call_next(request)
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
    return response
