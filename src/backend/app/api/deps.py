from app.control.adapters.openai_chat import ChatControl
from app.control.audit import EventAuditSink, EventSink, FanOutSink, LogEventSink
from app.control.guards.semantic_injection import (
    OpenAIInjectionClassifier,
    SemanticInjectionGuard,
)
from app.control.layer import ControlLayer, build_layer
from app.control.upstream import ChatUpstream, MockUpstream, OpenAIUpstream
from app.core.config import settings
from app.db.event_sink import DatabaseEventSink


def event_sink() -> EventSink:
    # Every event goes to the logs and to the database, where the dashboard
    # reads it.
    return FanOutSink(LogEventSink(), DatabaseEventSink())


def semantic_guard() -> SemanticInjectionGuard | None:
    # Without a key the demo runs offline, on the heuristic guard alone.
    if not settings.openai_api_key:
        return None
    classifier = OpenAIInjectionClassifier(
        settings.openai_api_key,
        settings.control_semantic_model,
        settings.control_semantic_timeout,
    )
    return SemanticInjectionGuard(
        classifier,
        threshold=settings.control_injection_threshold,
        fail_closed=settings.control_semantic_fail_closed,
        model=settings.control_semantic_model,
    )


def control_layer() -> ControlLayer:
    # Built on every request, so a setting changed at runtime applies to the
    # next one.
    return build_layer(
        settings.control_mode,
        settings.control_injection_threshold,
        EventAuditSink(event_sink()),
        semantic_guard(),
    )


def chat_control() -> ChatControl:
    upstream: ChatUpstream = (
        OpenAIUpstream(settings.openai_api_key, settings.openai_model)
        if settings.openai_api_key
        else MockUpstream()
    )
    return ChatControl(
        control_layer(), upstream, settings.control_log_payloads, event_sink()
    )
