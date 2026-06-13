"""Redis-backed shared memory: a runtime context layer for the agent chain.

Every agent in the personal -> cs -> research chain shares one memory space,
keyed by the A2A session id (== the incoming contextId). Facts written by one
agent become visible to the others within the same session. The memory is a
Redis JSON document stored at ``session:{contextId}``.

This file is copied into every agent image. Wire it into an agent by:
  - adding ``update_shared_memory`` to the agent's ``tools`` so it can WRITE
    facts (omit it for read-only agents), and
  - setting ``before_model_callback=inject_shared_memory`` so the current
    memory is injected into the system prompt on every LLM call.
"""

import os

import redis
from google.adk.agents.callback_context import CallbackContext
from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.models.llm_request import LlmRequest
from google.adk.tools import ToolContext

REDIS_URL = os.environ.get("REDIS_URL", "redis://host.docker.internal:6379/0")

# Shared client. decode_responses so RedisJSON values come back as Python types.
_redis = redis.Redis.from_url(REDIS_URL, decode_responses=True)

_KEY_PREFIX = "session:"


def _memory_key(context_id: str) -> str:
    return f"{_KEY_PREFIX}{context_id}"


def _context_id(context: ReadonlyContext) -> str:
    """Shared-memory key == the incoming A2A contextId. ADK keys its session on
    the contextId, so the session id is the contextId."""
    return context.session.id


def update_shared_memory(key: str, value: str, tool_context: ToolContext) -> str:
    """Store a fact in the session's shared memory so every agent can see it.

    Use this whenever you learn something durable about the user or the task
    (e.g. key="user_intent", value="buying a house"). The memory is a JSON
    object keyed by this session's contextId and shared across all agents.

    Args:
        key: The fact's name (e.g. "name", "user_intent", "income").
        value: The fact's value, as a string.

    Returns:
        A short confirmation string (or an error description on failure).
    """
    name = _memory_key(_context_id(tool_context))
    try:
        memory = _redis.json().get(name) or {}
        memory[key] = value
        _redis.json().set(name, "$", memory)
    except redis.RedisError as exc:
        return f"Could not update shared memory: {exc}"
    return f"Stored '{key}' in shared memory for this session."


def get_shared_memory(context_id: str) -> str:
    """Return the session's shared memory as a readable string.

    Helper (not an ADK tool): used by ``inject_shared_memory`` to render the
    current memory into the system prompt. Returns "Memory is empty." when
    nothing has been stored for this session yet.
    """
    try:
        memory = _redis.json().get(_memory_key(context_id))
    except redis.RedisError as exc:
        return f"Memory unavailable: {exc}"
    if not memory:
        return "Memory is empty."
    return "\n".join(f"- {key}: {value}" for key, value in memory.items())


def inject_shared_memory(
    callback_context: CallbackContext, llm_request: LlmRequest
) -> None:
    """ADK ``before_model_callback``: inject the session's shared memory into
    the system prompt on every LLM call.

    ``LlmAgent.instruction`` is fixed at construction, so this callback is how
    the prompt is refreshed per request with the live contents of shared
    memory. Returning ``None`` lets the model call proceed normally.
    """
    memory = get_shared_memory(_context_id(callback_context))
    llm_request.append_instructions(
        [
            "## Shared Memory (session context)\n"
            "Facts shared across all agents in this session:\n"
            f"{memory}"
        ]
    )
    return None
