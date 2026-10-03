from app.worker import celery_app


@celery_app.task
def ping() -> str:
    return "pong"
