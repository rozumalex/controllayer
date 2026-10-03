from functools import cache

from app.control.adapters.openai_chat import ChatControl
from app.control.layer import ControlLayer, build_layer
from app.control.upstream import ChatUpstream, MockUpstream, OpenAIUpstream
from app.core.config import settings


@cache
def control_layer() -> ControlLayer:
    return build_layer(settings.control_mode, settings.control_injection_threshold)


@cache
def chat_control() -> ChatControl:
    upstream: ChatUpstream = (
        OpenAIUpstream(settings.openai_api_key, settings.openai_model)
        if settings.openai_api_key
        else MockUpstream()
    )
    return ChatControl(control_layer(), upstream, settings.control_log_payloads)
