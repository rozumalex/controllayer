import json
import logging
from typing import Any

from sqlalchemy.exc import SQLAlchemyError

from app.db.models import ControlEvent
from app.db.session import SessionLocal

logger = logging.getLogger("app.control.events")


class DatabaseEventSink:
    """Saves each control layer event as a row of control_events."""

    async def write(self, event: dict[str, Any]) -> None:
        # JSONB takes only JSON types, so enums and the like become strings.
        data = json.loads(json.dumps(event, default=str))
        row = ControlEvent(
            trace_id=data["trace_id"],
            event=data["event"],
            action=data.get("action"),
            data=data,
        )
        try:
            async with SessionLocal() as session:
                session.add(row)
                await session.commit()
        except SQLAlchemyError, OSError:
            # The event is still in the logs. A database outage should not
            # take the chat down with it.
            logger.exception("could not save event: trace_id=%s", data["trace_id"])
