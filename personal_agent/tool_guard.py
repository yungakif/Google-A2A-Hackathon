"""Deterministic write-gate: dedupe identical mutating tool calls within a session.

The task reward is an exact whole-DB hash, so a *duplicate* write (same tool with
the same arguments) fails the task even when every required write also happened.
LLM prompting reduces but does not eliminate this. This guard enforces it in code:

- after_tool: cache each mutating call's result, keyed by (tool_name, args).
- before_tool: if an identical mutating call was already made this session, return
  the cached result WITHOUT re-executing — the duplicate env write never fires.

State lives in ToolContext.state, which is scoped to the A2A contextId, so sessions
stay fully isolated (no cross-conversation leakage). Read-only tools are never
deduped (a re-read must reflect current state). The set below is GENERIC — only
stable dispatcher / standard-action tool names, never task-specific discoverable
ids (those ride inside the args, so they key correctly without being hardcoded)."""

import json
from typing import Any, Optional

from google.adk.tools import BaseTool, ToolContext

# Tools that mutate the graded DB (or are idempotent dispatchers). Discoverable
# dispatchers carry the real tool name + args in their arguments, so a (name, args)
# key distinguishes distinct actions while catching exact repeats.
_MUTATING = {
    "call_discoverable_agent_tool",
    "call_discoverable_user_tool",
    "give_discoverable_user_tool",
    "unlock_discoverable_agent_tool",  # in-memory + idempotent; dedupe saves a round-trip
    "apply_for_credit_card",
    "submit_referral",
    "submit_transaction",
    "log_verification",
    "change_user_email",
    "request_human_agent_transfer",
    "transfer_to_human_agents",
}

_STATE_KEY = "_write_gate_seen"


def _key(tool_name: str, args: dict) -> str:
    try:
        return tool_name + "|" + json.dumps(args or {}, sort_keys=True, default=str)
    except Exception:
        return tool_name + "|" + repr(sorted((str(k), str(v)) for k, v in (args or {}).items()))


def dedupe_before_tool(
    tool: BaseTool, args: dict[str, Any], tool_context: ToolContext
) -> Optional[dict]:
    """Short-circuit an identical mutating call already made this session."""
    if tool.name not in _MUTATING:
        return None
    seen = tool_context.state.get(_STATE_KEY) or {}
    cached = seen.get(_key(tool.name, args))
    if cached is None:
        return None
    if isinstance(cached, dict):
        return {**cached, "deduplicated": "identical call already performed this session; not repeated"}
    return {"content": cached, "deduplicated": "identical call already performed this session; not repeated"}


def dedupe_after_tool(
    tool: BaseTool, args: dict[str, Any], tool_context: ToolContext, tool_response: dict
) -> Optional[dict]:
    """Record a mutating call's result so an identical repeat can be short-circuited."""
    if tool.name not in _MUTATING:
        return None
    seen = dict(tool_context.state.get(_STATE_KEY) or {})
    seen[_key(tool.name, args)] = tool_response
    tool_context.state[_STATE_KEY] = seen
    return None
