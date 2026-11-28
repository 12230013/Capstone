from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pymongo.errors import ConnectionFailure
from app.utils.sessions import require_session, allowed_origins
from app.services.presentation_access import presentation_scope
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from starlette.concurrency import run_in_threadpool
import asyncio
import logging
import os
import time
from pathlib import Path

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
from app.api.routes.case_access import require_cdr_case, require_relationship_case


async def reconcile_cims_drop(root, interval, stop):
    from app.services.cims_documents import reconcile

    observed = {}
    while not stop.is_set():
        try:
            observed = await run_in_threadpool(reconcile, root, observed)
        except Exception as exc:
            logging.getLogger(__name__).warning("CIMS scan failed (%s)", type(exc).__name__)
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
        except TimeoutError:
            pass


@asynccontextmanager
async def lifespan(app):
    ocr_config.validate_runtime()
    from acc_statements.index import embed, close_client
    started = time.monotonic()
    print("Preparing document search: loading and warming the embedding model...", flush=True)
    await run_in_threadpool(embed, ["Investigation document search warm-up"])
    # Provision the dedicated upload index at startup, including after a reset.
    # This validates existing schemas and never rebuilds the statement index.
    from app.ocr.qdrant_adapter import OCRQdrantAdapter
    await run_in_threadpool(OCRQdrantAdapter().provision_collection)
    print(f"Document search ready in {time.monotonic() - started:.1f}s. You can now submit questions.", flush=True)
    root = os.getenv("CIMS_DROP_ROOT")
    stop = asyncio.Event()
    worker = None
    if root:
        worker = asyncio.create_task(
            reconcile_cims_drop(Path(root), max(10, int(os.getenv("CIMS_DROP_INTERVAL", "60"))), stop)
        )
    try:
        yield
    finally:
        stop.set()
        if worker is not None:
            await worker
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
app.include_router(cdr_router, dependencies=[Depends(require_cdr_case)])
app.include_router(relationship_router, dependencies=[Depends(require_relationship_case)])
app.include_router(auth_router)
app.include_router(cims_router)
def require_legacy_statement_access(session: dict = Depends(require_session)):
    if presentation_scope(session) is not None:
        raise HTTPException(403, "Use case chat to access presentation statements.")


app.include_router(statements_router, dependencies=[Depends(require_legacy_statement_access)])
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
