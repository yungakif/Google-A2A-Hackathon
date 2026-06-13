"""Tool that lets the personal agent talk to the bank's customer service
agent over A2A, propagating the current session's contextId so both agents
(and the env) share one conversation identity."""

import os
import uuid

import httpx
from a2a.client import ClientConfig, ClientFactory, minimal_agent_card
from a2a.types import Message, Part, Role, Task, TextPart
from google.adk.tools import ToolContext

from env_toolset import session_id

CS_AGENT_URL = os.environ["CS_AGENT_URL"]

# Strictly LESS than the harness's fixed 300s budgets (the bridge's per-turn
# timeout and the gateway's CS-forward timeout are both 300s). If we waited the
# full 300s, a slow CS turn would trip the harness bridge at the same instant
# and surface as an A2AClientTimeoutError -> INFRASTRUCTURE_ERROR (reward 0,
# and the task drops from the cross-team completed set). Capping below 300s
# leaves the personal agent slack to catch the timeout and still return a
# graceful reply to the user within the turn.
_TIMEOUT_S = 240.0


def _text_of_message(message: Message) -> str:
    texts = []
    for part in message.parts or []:
        root = getattr(part, "root", part)
        if isinstance(root, TextPart) and root.text:
            texts.append(root.text)
    return "\n".join(texts)


def _text_of_task(task: Task) -> str:
    texts = []
    for artifact in task.artifacts or []:
        for part in artifact.parts or []:
            root = getattr(part, "root", part)
            if isinstance(root, TextPart) and root.text:
                texts.append(root.text)
    if task.status is not None and task.status.message is not None:
        text = _text_of_message(task.status.message)
        if text:
            texts.append(text)
    return "\n".join(texts)


async def ask_customer_service(message: str, tool_context: ToolContext) -> str:
    """Send a message to the bank's customer service agent and return its reply.

    The conversation with customer service persists for this whole session,
    so you can ask follow-up questions and they will remember the context.
    """
    outgoing = Message(
        message_id=uuid.uuid4().hex,
        role=Role.user,
        parts=[Part(root=TextPart(text=message))],
        context_id=session_id(tool_context),
    )
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_S) as http_client:
            client = ClientFactory(
                ClientConfig(streaming=False, httpx_client=http_client)
            ).create(minimal_agent_card(CS_AGENT_URL, ["JSONRPC"]))
            reply = ""
            async for event in client.send_message(outgoing):
                if isinstance(event, Message):
                    reply = _text_of_message(event) or reply
                elif isinstance(event, tuple) and isinstance(event[0], Task):
                    reply = _text_of_task(event[0]) or reply
    except Exception as exc:
        # Degrade gracefully: never let a timeout/disconnect propagate out of the
        # tool. A raised exception would abort the whole personal turn and the
        # harness scores it INFRASTRUCTURE_ERROR; returning text lets the model
        # apologise / retry and the turn still completes normally.
        return (
            f"[customer service did not respond ({type(exc).__name__}). It may be "
            "busy. Tell the user you couldn't reach customer service just now and "
            "offer to try again, or proceed with anything you can do directly.]"
        )
    return reply or "[no response from customer service]"
