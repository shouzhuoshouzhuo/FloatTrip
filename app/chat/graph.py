"""Single LLM-powered conversation understanding graph."""

from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from app.chat.models import DialogueDecision, DialogueUnderstandingError
from app.chat.prompts import dialogue_messages
from app.llm.factory import build_structured_llm
from app.planning.helpers import ainvoke_structured


class ChatState(TypedDict, total=False):
    dialogue_context: dict[str, Any]
    decision: dict[str, Any]
    response: str


async def dialogue_agent_node(
    state: ChatState,
    *,
    llm: Any | None = None,
) -> dict[str, Any]:
    """Call the structured LLM once, with one safe schema-repair attempt."""
    client = llm or build_structured_llm(DialogueDecision, temperature=0)
    context = state.get("dialogue_context") or {}
    messages = dialogue_messages(context)
    last_error: Exception | None = None
    for attempt in range(2):
        try:
            result = await ainvoke_structured(client, messages, retries=1)
            decision = (
                result
                if isinstance(result, DialogueDecision)
                else DialogueDecision.model_validate(result)
            )
            return {
                "decision": decision.model_dump(mode="json"),
                "response": decision.reply,
            }
        except Exception as exc:  # schema/provider errors are intentionally opaque
            last_error = exc
            if attempt == 0:
                messages = [
                    *messages,
                    (
                        "human",
                        "上一份结构化结果未通过校验。请只按既定 schema 重新输出，"
                        "不要添加字段，也不要解释错误。",
                    ),
                ]
    raise DialogueUnderstandingError() from last_error


def build_chat_graph(checkpointer=None, *, llm: Any | None = None):
    graph = StateGraph(ChatState)

    async def dialogue_agent(state: ChatState) -> dict[str, Any]:
        return await dialogue_agent_node(state, llm=llm)

    graph.add_node("dialogue_agent", dialogue_agent)
    graph.add_edge(START, "dialogue_agent")
    graph.add_edge("dialogue_agent", END)
    return graph.compile(checkpointer=checkpointer)
