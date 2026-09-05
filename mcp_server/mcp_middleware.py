"""Per-caller rate limiting and audit logging around every tool call."""

import logging
import os

from fastmcp.server.dependencies import get_access_token
from fastmcp.server.middleware import Middleware
from fastmcp.server.middleware.rate_limiting import RateLimitError, SlidingWindowRateLimiter

LOG_FILE = os.environ.get('MCP_TOOL_CALL_LOG_FILE', os.path.join(os.path.dirname(__file__), 'tool_calls.log'))

logger = logging.getLogger('mcp_server')
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.FileHandler(LOG_FILE)
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
    logger.addHandler(handler)

# Never logged in full - a tool argument, not something to write to a log file.
REDACTED_ARGS = ('new_password',)


def _caller_id():
    """The signed-in caller's Google subject, or 'anonymous' outside a request."""
    access_token = get_access_token()
    return access_token.claims.get('sub', 'unknown') if access_token else 'anonymous'


class ToolCallRateLimiter(Middleware):
    """Caps how many tool calls each caller can make in a rolling time window,
    independent of every other caller.
    """

    def __init__(self, max_calls=5, window_minutes=1):
        self._max_calls = max_calls
        self._window_minutes = window_minutes
        self._windows = {}

    async def on_call_tool(self, context, call_next):
        caller = _caller_id()
        window = self._windows.setdefault(
            caller, SlidingWindowRateLimiter(self._max_calls, self._window_minutes * 60)
        )
        if not await window.is_allowed():
            raise RateLimitError(
                f'Rate limit exceeded for caller {caller!r}: '
                f'{self._max_calls} calls per {self._window_minutes} minute(s).'
            )
        return await call_next(context)


class ToolCallLogger(Middleware):
    """Logs every tool call - caller, tool, arguments - and whether it succeeded."""

    def __init__(self, redact=REDACTED_ARGS):
        self._redact = redact

    async def on_call_tool(self, context, call_next):
        caller = _caller_id()
        tool = context.message.name
        args = {
            key: ('***' if key in self._redact else value)
            for key, value in (context.message.arguments or {}).items()
        }

        try:
            result = await call_next(context)
        except Exception:
            logger.exception('tool call failed: caller=%s tool=%s args=%s', caller, tool, args)
            raise

        logger.info('tool call: caller=%s tool=%s args=%s', caller, tool, args)
        return result
