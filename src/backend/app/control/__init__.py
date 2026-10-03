"""The control layer: a pipeline of guards between agents and their tools.

It has no FastAPI or MCP imports, so any transport can wrap it.
"""

import logging

# Uvicorn leaves the root logger at WARNING, so the control layer's logs need
# their own handler to show up in the container logs.
logger = logging.getLogger("app.control")
logger.setLevel(logging.INFO)
if not logger.handlers:
    logger.addHandler(logging.StreamHandler())
