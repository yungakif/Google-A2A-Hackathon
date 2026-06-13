"""Tool that lets the customer service agent talk to the research agent over
A2A, propagating the current session's contextId so all agents (and the env)
share one conversation identity down the personal -> cs -> research chain."""

import os
import uuid

import httpx
from a2a.client import ClientConfig, ClientFactory, minimal_agent_card
from a2a.types import Message, Part, Role, Task, TextPart
from google.adk.tools import ToolContext

from env_toolset import session_id

# Optional: empty/unset when no research agent is wired in (e.g. a held-out
# pairing). The tool degrades gracefully rather than crashing at import or call.
RESEARCH_AGENT_URL = os.environ.get("RESEARCH_AGENT_URL", "").strip()

# Kept well under the 5-minute per-turn budget so a slow/hung research agent
# can never push a CS turn into a timeout (scored 0).
_TIMEOUT_S = 90.0

_UNAVAILABLE = (
    "[research agent unavailable; answer from the knowledge base (kb_search) "
    "yourself — do not wait on research.]"
)


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


async def ask_research_agent(message: str, tool_context: ToolContext) -> str:
    """Send a message to the research agent and return its reply.

    The conversation with the research agent persists for this whole session,
    so you can ask follow-up questions and it will remember the context.
    """
    if not RESEARCH_AGENT_URL:
        return _UNAVAILABLE
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
            ).create(minimal_agent_card(RESEARCH_AGENT_URL, ["JSONRPC"]))
            reply = ""
            async for event in client.send_message(outgoing):
                if isinstance(event, Message):
                    reply = _text_of_message(event) or reply
                elif isinstance(event, tuple) and isinstance(event[0], Task):
                    reply = _text_of_task(event[0]) or reply
    except Exception:
        # Unreachable / timeout / protocol error — never fail the CS turn.
        return _UNAVAILABLE
    return reply or _UNAVAILABLE
