"""In-turn unlock->call sequencer for agent-discoverable tools.

The env surfaces a newly-unlocked discoverable tool as a typed tool only on the
NEXT model turn, so the natural "unlock, wait for it to appear, then call"
pattern costs two ordered model round-trips per tool — the dominant timeout /
max-steps driver, and a frequent point of failure when the model unlocks but
never gets around to the call. This collapses the pair into ONE tool call: it
POSTs the unlock and then the call back-to-back in the same turn through the
existing env API, so the whole unlock->call action completes with no turn
boundary in between.

Re-unlocking is safe (a stray unlock writes no graded DB row; only a stray CALL
is fatal), so for a procedure that needs N calls you invoke this once per
argument set — each invocation re-unlocks (a harmless no-op) and makes exactly
one call.
"""

import json

from google.adk.tools import ToolContext

from env_toolset import _post_tool_call, session_id


async def unlock_and_call(
    agent_tool_name: str, arguments_json: str, tool_context: ToolContext
) -> dict:
    """Unlock an agent-discoverable tool AND call it, in a single step.

    PREFER THIS over calling `unlock_discoverable_agent_tool` and then
    `call_discoverable_agent_tool` as two separate steps: doing both here, in
    one turn, avoids a wasted round-trip and guarantees the call actually
    happens after the unlock (splitting them across turns is a common way the
    call gets dropped). For a procedure that requires several calls, invoke this
    once per argument set.

    Args:
        agent_tool_name: The exact discoverable tool name from the knowledge
            base (e.g. "calculate_apr_adjustment_7842").
        arguments_json: JSON object string of the tool's arguments, e.g.
            '{"user_id": "abc123", "amount": 1500}'. Use '{}' if there are none.

    Returns:
        The discoverable tool's result. If the arguments are not valid JSON, or
        the unlock step errors, that error is returned and the call is skipped.
    """
    try:
        json.loads(arguments_json or "{}")
    except json.JSONDecodeError as e:
        return {"error": True, "content": f"Invalid arguments_json ({e}); nothing called."}

    sid = session_id(tool_context)
    unlock = await _post_tool_call(
        sid, "unlock_discoverable_agent_tool", {"agent_tool_name": agent_tool_name}
    )
    if isinstance(unlock, dict) and unlock.get("error"):
        return {
            "error": True,
            "content": f"unlock failed for '{agent_tool_name}': {unlock.get('content')}",
            "unlock_result": unlock,
        }
    return await _post_tool_call(
        sid,
        "call_discoverable_agent_tool",
        {"agent_tool_name": agent_tool_name, "arguments": arguments_json or "{}"},
    )
