from app.agents.executor import execute_workflow
from app.database import SessionLocal
from app.services.documents import process_document as _process_document
from app.utils.logging import setup_logging
from app.config import get_settings
from app.workers.celery_app import celery_app

setup_logging(get_settings().log_level)


@celery_app.task(name="agentflow.run_workflow", bind=True, max_retries=0)
def run_workflow(self, workflow_id: int) -> None:
    execute_workflow(workflow_id)


@celery_app.task(name="agentflow.process_document", bind=True, max_retries=0)
def process_document(self, document_id: int) -> None:
    db = SessionLocal()
    try:
        _process_document(db, document_id)
    finally:
        db.close()
