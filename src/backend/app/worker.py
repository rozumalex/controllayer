from celery import Celery
from celery.schedules import crontab

from app.core.config import settings
from app.core.sentry import init_sentry

init_sentry()

# Run the worker and the scheduler together in one process:
# celery -A app.worker worker --beat. Run one copy only, because every
# scheduler sends the scheduled tasks again.
celery_app = Celery("app", broker=settings.redis_url, include=["app.tasks.ping"])

# On a deploy, the worker waits up to 60 seconds for the running tasks to
# finish (see .do/app.yaml). Acknowledge a task when it ends, not when it
# starts, so a task that runs longer and gets killed goes back to the queue and
# runs again. Write tasks that are safe to run twice.
celery_app.conf.task_acks_late = True
celery_app.conf.task_reject_on_worker_lost = True
# Redis hands an unacknowledged task to a worker again after this many seconds,
# so a killed task runs again after 5 minutes, not the default hour. Keep it
# longer than the longest task, or a running task starts a second time.
celery_app.conf.broker_transport_options = {"visibility_timeout": 300}

celery_app.conf.beat_schedule = {
    "ping-every-minute": {"task": "app.tasks.ping.ping", "schedule": crontab()},
}
