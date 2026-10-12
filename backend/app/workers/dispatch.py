"""Enqueue background work on Celery (default) or in a local thread when CELERY_EAGER=true (dev only)."""
import threading

from app.config import get_settings
from app.workers import tasks


def _thread(fn, *args):
    threading.Thread(target=fn, args=args, daemon=True).start()


def dispatch_workflow(workflow_id: int) -> None:
    if get_settings().celery_eager:
        _thread(tasks.run_workflow.run, workflow_id)
    else:
        tasks.run_workflow.delay(workflow_id)


def dispatch_document(document_id: int) -> None:
    if get_settings().celery_eager:
        _thread(tasks.process_document.run, document_id)
    else:
        tasks.process_document.delay(document_id)
