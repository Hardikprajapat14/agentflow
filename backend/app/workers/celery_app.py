from celery import Celery

from app.config import get_settings

s = get_settings()
celery_app = Celery("agentflow", broker=s.redis_url, backend=s.redis_url, include=["app.workers.tasks"])
celery_app.conf.update(task_acks_late=True, worker_prefetch_multiplier=1, task_time_limit=1800,
                       task_soft_time_limit=1700, task_track_started=True, broker_connection_retry_on_startup=True,
                       result_expires=3600)
