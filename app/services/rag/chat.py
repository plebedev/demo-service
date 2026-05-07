"""Bounded RAG chat planning and answer drafting."""

from __future__ import annotations

from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.usage import UsageLimits

from app.core.config import Settings
from app.models.rag import RagMessage, RagPersona
from app.services.model_factory import create_model, create_provider_model_settings
from app.services.rag.models import RagSearchResult
from app.workflows.config_models import WorkflowProvider


class RagTurnPlan(BaseModel):
    """Structured plan for one RAG chat turn."""

    is_allowed: bool
    refusal_reason: str | None = None
    user_facing_refusal: str | None = None
    needs_retrieval: bool = True
    search_queries: list[str] = Field(default_factory=list, max_length=3)


class RagAssistantDraft(BaseModel):
    """Structured assistant response draft."""

    content_markdown: str = Field(min_length=1)
    citation_chunk_ids: list[int] = Field(default_factory=list)


class RagChatService:
    """LLM-backed helper for bounded RAG chat turns."""

    async def plan_turn(
        self,
        *,
        settings: Settings,
        persona: RagPersona,
        recent_messages: list[RagMessage],
        user_content: str,
    ) -> RagTurnPlan:
        """Classify scope and extract semantic search queries."""
        provider = WorkflowProvider(settings.rag_chat_provider)
        model = create_model(provider, settings.rag_chat_model, settings)
        agent = Agent(
            model=model,
            instructions=_planner_instructions(persona),
            output_type=RagTurnPlan,
            model_settings=create_provider_model_settings(
                provider=provider,
                timeout=30,
                temperature=0,
                max_tokens=500,
            ),
        )
        result = await agent.run(
            _planner_prompt(recent_messages=recent_messages, user_content=user_content),
            usage_limits=UsageLimits(request_limit=1, tool_calls_limit=0),
        )
        return result.output

    async def draft_answer(
        self,
        *,
        settings: Settings,
        persona: RagPersona,
        recent_messages: list[RagMessage],
        user_content: str,
        retrieved_chunks: list[RagSearchResult],
    ) -> RagAssistantDraft:
        """Draft a grounded answer using retrieved persona-scoped chunks."""
        provider = WorkflowProvider(settings.rag_chat_provider)
        model = create_model(provider, settings.rag_chat_model, settings)
        agent = Agent(
            model=model,
            instructions=_answer_instructions(persona),
            output_type=RagAssistantDraft,
            model_settings=create_provider_model_settings(
                provider=provider,
                timeout=45,
                temperature=settings.rag_chat_temperature,
                max_tokens=settings.rag_chat_max_tokens,
            ),
        )
        result = await agent.run(
            _answer_prompt(
                recent_messages=recent_messages,
                user_content=user_content,
                retrieved_chunks=retrieved_chunks,
            ),
            usage_limits=UsageLimits(request_limit=1, tool_calls_limit=0),
        )
        return result.output


def _planner_instructions(persona: RagPersona) -> str:
    return (
        "You plan one bounded RAG demo chat turn. Decide whether the user request "
        "fits the selected persona. Use the persona capabilities as the boundary "
        "for off-topic questions. If the request is outside scope, return a brief "
        "user-facing refusal that says what this persona can help with. If the "
        "request is allowed, extract one to three concise semantic search queries "
        "for document retrieval. Do not include conversational filler in search "
        "queries.\n\n"
        f"Persona name: {persona.name}\n"
        f"Persona instructions:\n{persona.instructions}\n\n"
        f"Persona capabilities:\n{persona.capabilities_serialized or 'Not specified.'}"
    )


def _answer_instructions(persona: RagPersona) -> str:
    return (
        "You are a bounded retrieval-grounded assistant. Answer only for the "
        "selected persona. Use retrieved context when document knowledge is "
        "requested. If the retrieved context is insufficient, say so plainly. "
        "Do not invent facts, documents, or citations. Return markdown content "
        "and cite only chunk ids that were actually useful.\n\n"
        f"Persona name: {persona.name}\n"
        f"Persona instructions:\n{persona.instructions}\n\n"
        f"Persona capabilities:\n{persona.capabilities_serialized or 'Not specified.'}"
    )


def _planner_prompt(
    *,
    recent_messages: list[RagMessage],
    user_content: str,
) -> str:
    return (
        f"Recent conversation:\n{_format_recent_messages(recent_messages)}\n\n"
        f"Latest user message:\n{user_content}"
    )


def _answer_prompt(
    *,
    recent_messages: list[RagMessage],
    user_content: str,
    retrieved_chunks: list[RagSearchResult],
) -> str:
    return (
        f"Retrieved context:\n{_format_retrieved_chunks(retrieved_chunks)}\n\n"
        f"Recent conversation:\n{_format_recent_messages(recent_messages)}\n\n"
        f"Latest user message:\n{user_content}"
    )


def _format_recent_messages(messages: list[RagMessage]) -> str:
    if not messages:
        return "No previous messages."
    return "\n".join(
        f"{message.role} [{message.turn_index}]: {message.content}"
        for message in messages[-8:]
    )


def _format_retrieved_chunks(chunks: list[RagSearchResult]) -> str:
    if not chunks:
        return "No retrieved context."
    return "\n\n".join(
        (
            f"Chunk id: {chunk.chunk_id}\n"
            f"Document id: {chunk.document_id}\n"
            f"Title: {chunk.title or 'Untitled'}\n"
            f"Source: {chunk.source}\n"
            f"Chunk index: {chunk.chunk_index}\n"
            f"Text:\n{chunk.chunk_text}"
        )
        for chunk in chunks
    )
