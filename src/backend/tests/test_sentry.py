from collections.abc import Iterator

import pytest
import sentry_sdk

from app.core.config import settings
from app.core.sentry import init_sentry


@pytest.fixture(autouse=True)
def close_sentry() -> Iterator[None]:
    yield
    sentry_sdk.get_client().close()


def test_init_sentry_without_dsn(monkeypatch: pytest.MonkeyPatch) -> None:
    # given
    monkeypatch.setattr(settings, "sentry_dsn", "")

    # when
    init_sentry()

    # then
    assert not sentry_sdk.get_client().is_active()


def test_init_sentry_with_dsn(monkeypatch: pytest.MonkeyPatch) -> None:
    # given
    monkeypatch.setattr(settings, "sentry_dsn", "https://key@example.com/1")

    # when
    init_sentry()

    # then
    assert sentry_sdk.get_client().is_active()
