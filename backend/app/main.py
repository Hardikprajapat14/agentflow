import logging
import os
import time
import uuid

import redis
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.config import get_settings
from app.database import engine
from app.routers import auth, documents, workflows
from app.utils.logging import setup_logging

settings = get_settings()
setup_logging(settings.log_level)
logger = logging.getLogger("agentflow")

app = FastAPI(title="AgentFlow API", version="1.0.0", description="Autonomous AI workforce & workflow automation platform",
              docs_url="/api/docs", openapi_url="/api/openapi.json")
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origin_list, allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def request_context(request: Request, call_next):
    rid, start = uuid.uuid4().hex[:8], time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:  # noqa: BLE001
        logger.exception("[%s] unhandled error on %s %s", rid, request.method, request.url.path)
        response = JSONResponse({"detail": "Internal server error", "request_id": rid}, status_code=500)
    response.headers.update({"X-Request-ID": rid, "X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY",
                             "Referrer-Policy": "no-referrer"})
    logger.info("[%s] %s %s -> %s (%.0f ms)", rid, request.method, request.url.path, response.status_code,
                (time.perf_counter() - start) * 1000)
    return response


for r in (auth.router, documents.router, workflows.router):
    app.include_router(r, prefix="/api")


@app.get("/api/health", tags=["system"])
def health():
    checks = {}
    try:
        with engine.connect() as c:
            c.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:  # noqa: BLE001
        checks["database"] = f"error: {exc.__class__.__name__}"
    try:
        redis.Redis.from_url(settings.redis_url, socket_connect_timeout=2).ping()
        checks["redis"] = "ok"
    except Exception as exc:  # noqa: BLE001
        checks["redis"] = f"error: {exc.__class__.__name__}" if not settings.celery_eager else "skipped (eager mode)"
    checks["llm"] = "configured" if settings.llm_api_key else "missing LLM_API_KEY"
    ok = checks["database"] == "ok"
    return JSONResponse({"status": "ok" if ok else "degraded", **checks}, status_code=200 if ok else 503)


@app.on_event("startup")
def resume_interrupted_workflows() -> None:
    """With CELERY_EAGER (single-process hosting) a restart kills in-flight threads; pick those workflows back up."""
    if not settings.celery_eager:
        return
    from app.database import SessionLocal
    from app.models import Workflow
    from app.workers.dispatch import dispatch_workflow

    try:
        with SessionLocal() as db:
            ids = [w.id for w in db.query(Workflow).filter(Workflow.status.in_(["pending", "planning", "running"]))]
        for wid in ids:
            logger.info("Resuming interrupted workflow %s", wid)
            dispatch_workflow(wid)
    except Exception:  # noqa: BLE001
        logger.exception("Could not resume interrupted workflows")
