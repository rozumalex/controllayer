import sentry_sdk

from app.core.config import settings


def init_sentry() -> None:
    """Send errors and traces to Sentry. Does nothing without SENTRY_DSN.

    The SDK turns on its FastAPI, Celery, SQLAlchemy and Redis integrations by
    itself when those packages are installed.
    """
    if not settings.sentry_dsn:
        return
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.sentry_environment,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        send_default_pii=False,
    )
