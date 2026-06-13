"""Redis-backed shared context layer for the personal -> cs -> research chain.

This is the runtime context layer (Redis Agent Memory): facts gathered by one
agent — the user's record, a verified identity, a resolved procedure, the exact
discoverable tool name + args, a mid-session decision — are written here and
become visible to every other agent in the SAME session, so the trio learns,
remembers, and collaborates instead of each agent re-deriving everything.

INTEROP CONTRACT (this is load-bearing — half the score pairs your agents with
strangers who will NOT share this store):
  * The store is keyed STRICTLY by the A2A contextId (`session:{contextId}`),
    so concurrent conversations are fully isolated (statelessness rule) and a
    held-out partner's session never collides with yours.
  * It is a pure ACCELERATOR. Every read tolerates a miss and every write
    tolerates failure: if Redis is down, the key is empty, or the partner agent
    never wrote it, the agent must still compute the correct answer from
    scratch. Never DEPEND on a value a partner wrote — only use it to skip work.
  * Writes set a TTL so keys from finished sims expire instead of accumulating.

This file is copied into every agent image and wired in by:
  * `before_model_callback=inject_context` — render the live store into the
    system prompt on every LLM call (read path), and
  * adding `remember_context` to an agent's `tools` so it can WRITE facts.
"""

import os

import redis
from google.adk.agents.callback_context import CallbackContext
from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.models.llm_request import LlmRequest
from google.adk.tools import ToolContext

REDIS_URL = os.environ.get("REDIS_URL", "redis://host.docker.internal:6379/0")

# How long a session's context lives after its last write. Comfortably longer
# than the 10-minute task budget, short enough that finished sims expire.
_TTL_SECONDS = int(os.environ.get("CONTEXT_TTL_SECONDS", "3600"))
_KEY_PREFIX = "session:"

# decode_responses so RedisJSON values come back as Python types. A failure to
# connect here must never crash the agent, so the client is created lazily and
# every operation is guarded.
_redis = None


def _client():
    global _redis
    if _redis is None:
        _redis = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    return _redis


def _key(context_id: str) -> str:
    return f"{_KEY_PREFIX}{context_id}"


def _context_id(context: ReadonlyContext) -> str:
    """Store key == the incoming A2A contextId. ADK keys its session on the
    contextId, so the session id IS the contextId."""
    return context.session.id


def read_context(context_id: str) -> dict:
    """Return this session's shared context as a dict (empty on miss/failure)."""
    try:
        return _client().json().get(_key(context_id)) or {}
    except Exception:
        # Redis down / key absent / wrong type — degrade to "no context".
        return {}


def write_context(context_id: str, key: str, value: str) -> bool:
    """Merge one fact into this session's shared context. Returns success.

    Best-effort: a failure is swallowed (the agent proceeds without the cache).
    """
    try:
        client = _client()
        name = _key(context_id)
        memory = client.json().get(name) or {}
        memory[str(key)] = value
        client.json().set(name, "$", memory)
        client.expire(name, _TTL_SECONDS)
        return True
    except Exception:
        return False


def remember_context(key: str, value: str, tool_context: ToolContext) -> str:
    """Save a durable fact about the user or task into the session's shared
    context so every agent in this conversation can see it.

    Use this when you learn something worth reusing: a verified identity, the
    user's record fields, the resolved procedure, the exact discoverable tool
    name and its arguments, or a decision already made. Do NOT store secrets you
    have not yet verified, and never rely on a fact being present — it is a
    cache, not a source of truth.

    Args:
        key: Short name for the fact (e.g. "verified", "user_id", "procedure").
        value: The fact's value, as a string.

    Returns:
        A short confirmation (or a note that the store was unavailable).
    """
    ok = write_context(_context_id(tool_context), key, value)
    return (
        f"Saved '{key}' to shared session context."
        if ok
        else f"Note: shared context unavailable; '{key}' not cached (continuing anyway)."
    )


def render_context(context_id: str) -> str:
    """Human-readable rendering of the session context for prompt injection."""
    memory = read_context(context_id)
    if not memory:
        return "(empty — nothing has been gathered for this session yet)"
    return "\n".join(f"- {key}: {value}" for key, value in memory.items())


def inject_context(
    callback_context: CallbackContext, llm_request: LlmRequest
) -> None:
    """ADK `before_model_callback`: inject the live session context into the
    system prompt on every LLM call. Returning None lets the call proceed.

    `LlmAgent.instruction` is fixed at construction, so this is how the prompt
    is refreshed per request with whatever the chain has gathered so far. It is
    purely additive context — the agent must still work if it is empty.
    """
    rendered = render_context(_context_id(callback_context))
    llm_request.append_instructions(
        [
            "## Shared Session Context (Redis runtime context layer)\n"
            "Facts gathered by the agents in THIS session (a cache — verify "
            "anything you act on, and work normally if this is empty):\n"
            f"{rendered}"
        ]
    )
    return None
