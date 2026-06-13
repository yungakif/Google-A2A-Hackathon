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

RESEARCH_AGENT_URL = os.environ["RESEARCH_AGENT_URL"]

_TIMEOUT_S = 300.0


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
    outgoing = Message(
        message_id=uuid.uuid4().hex,
        role=Role.user,
        parts=[Part(root=TextPart(text=message))],
        context_id=session_id(tool_context),
    )
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
    return reply or "[no response from research agent]"
