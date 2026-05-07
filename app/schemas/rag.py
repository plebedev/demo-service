"""Pydantic schemas for protected RAG document and persona APIs."""

from datetime import datetime

from pydantic import BaseModel, Field


class RagDocumentIngestResponse(BaseModel):
    """Summary returned after a document has been chunked and embedded."""

    document_id: int = Field(description="Database ID of the ingested document")
    source: str = Field(description="Original filename or URL of the document")
    title: str | None = Field(description="Optional display title for the document")
    labels: list[str] = Field(description="Search labels assigned to this document")
    chunk_count: int = Field(
        description="Number of text chunks created during ingestion"
    )
    reused_existing_document: bool = Field(
        default=False,
        description="True when an existing document with matching content was reused",
    )


class RagSearchRequest(BaseModel):
    """Request body for label-constrained vector search."""

    query: str = Field(
        min_length=1,
        max_length=4000,
        description="Search query text to embed and match against stored chunks",
    )
    labels: list[str] = Field(
        min_length=1,
        description="One or more label keys that restrict the chunk search scope",
    )
    limit: int = Field(
        default=5, ge=1, le=20, description="Maximum number of chunks to return"
    )


class RagSearchResultResponse(BaseModel):
    """One chunk returned from label-constrained vector search."""

    chunk_id: int = Field(description="Database ID of the matched chunk")
    document_id: int = Field(description="Database ID of the parent document")
    source: str = Field(description="Source filename or URL of the parent document")
    title: str | None = Field(
        description="Optional display title of the parent document"
    )
    chunk_index: int = Field(
        description="Zero-based position of this chunk within its document"
    )
    chunk_text: str = Field(description="Text content of the matched chunk")
    distance: float = Field(
        description="Cosine distance between query and chunk embeddings; lower is more similar"
    )


class RagSearchResponse(BaseModel):
    """Search response wrapper."""

    results: list[RagSearchResultResponse] = Field(
        description="Ranked list of matching chunks ordered by ascending distance"
    )


class RagPersonaCreateRequest(BaseModel):
    """Payload for creating a RAG assistant persona."""

    name: str = Field(
        min_length=1, max_length=255, description="Display name for the persona"
    )
    instructions: str = Field(
        min_length=1,
        max_length=8000,
        description="System-level instructions that shape the persona's responses",
    )
    capabilities: str | None = Field(
        default=None,
        max_length=8000,
        description="Optional description of persona capabilities shown to the user",
    )
    tool_config: str | None = Field(
        default=None,
        max_length=8000,
        description="Optional JSON tool configuration for this persona",
    )


class RagPersonaUpdateRequest(BaseModel):
    """Payload for updating a RAG assistant persona."""

    name: str = Field(min_length=1, max_length=255, description="Updated display name")
    instructions: str = Field(
        min_length=1,
        max_length=8000,
        description="Updated system-level instructions",
    )
    capabilities: str | None = Field(
        default=None,
        max_length=8000,
        description="Updated capabilities description",
    )
    tool_config: str | None = Field(
        default=None,
        max_length=8000,
        description="Updated tool configuration JSON",
    )


class RagPersonaResponse(BaseModel):
    """Serialized RAG assistant persona."""

    id: int = Field(description="Database ID of the persona")
    name: str = Field(description="Display name")
    instructions: str = Field(description="System-level instructions")
    capabilities: str | None = Field(description="Optional capabilities description")
    tool_config: str | None = Field(description="Optional tool configuration JSON")
    is_active: bool = Field(description="False when the persona has been soft-deleted")
    created_at: datetime = Field(description="Timestamp when the persona was created")
    updated_at: datetime = Field(description="Timestamp of the last update")


class RagPersonaListResponse(BaseModel):
    """List wrapper for tenant-scoped RAG personas."""

    personas: list[RagPersonaResponse] = Field(
        description="Tenant-scoped personas ordered by creation date"
    )


class RagPersonaDocumentResponse(BaseModel):
    """Document linked to a RAG persona."""

    document_id: int = Field(description="Database ID of the linked document")
    source: str = Field(description="Original filename or URL")
    title: str | None = Field(description="Optional display title")
    display_name: str | None = Field(
        description="Override label shown to the user in place of the source filename"
    )
    chunk_count: int = Field(
        description="Number of stored text chunks for this document"
    )
    linked_at: datetime = Field(
        description="Timestamp when the document was linked to the persona"
    )


class RagPersonaDocumentListResponse(BaseModel):
    """Documents linked to one RAG persona."""

    documents: list[RagPersonaDocumentResponse] = Field(
        description="Documents linked to the persona ordered by link time"
    )


class RagPersonaDocumentIngestResponse(BaseModel):
    """Response returned after linking or ingesting a persona document."""

    document: RagPersonaDocumentResponse = Field(
        description="Metadata of the linked document"
    )
    reused_existing_document: bool = Field(
        description="True when content hash matched an existing document"
    )


class RagConversationCreateRequest(BaseModel):
    """Payload for creating a RAG chat conversation."""

    persona_id: int = Field(description="ID of the persona to converse with")
    title: str | None = Field(
        default=None,
        max_length=255,
        description="Optional display title for the conversation",
    )


class RagMessageResponse(BaseModel):
    """Stored RAG conversation message."""

    id: int = Field(description="Database ID of the message")
    role: str = Field(description="Message author role: 'user' or 'assistant'")
    content: str = Field(description="Text content of the message")
    turn_index: int = Field(
        description="Zero-based turn number within the conversation"
    )
    metadata: str | None = Field(
        description="Optional serialized metadata attached to the message"
    )
    created_at: datetime = Field(description="Timestamp when the message was stored")


class RagMessageCitationResponse(BaseModel):
    """Citation attached to an assistant RAG message."""

    id: int = Field(description="Database ID of the citation")
    message_id: int = Field(
        description="ID of the assistant message this citation belongs to"
    )
    document_id: int = Field(description="ID of the source document")
    chunk_id: int = Field(description="ID of the specific retrieved chunk")
    chunk_index: int = Field(
        description="Zero-based position of the chunk within its document"
    )
    source: str = Field(description="Source filename or URL of the parent document")
    title: str | None = Field(
        description="Optional display title of the parent document"
    )
    snippet: str = Field(description="Excerpt from the chunk shown to the user")
    rank: int = Field(
        description="Rank among results for this turn; lower means more relevant"
    )


class RagConversationResponse(BaseModel):
    """Serialized RAG conversation summary."""

    id: int = Field(description="Database ID of the conversation")
    persona_id: int | None = Field(
        description="ID of the linked persona; null if the persona was deleted"
    )
    persona_name: str | None = Field(
        description="Display name of the linked persona at query time"
    )
    title: str | None = Field(description="Optional display title")
    status: str = Field(
        description="Conversation lifecycle status: 'active' or 'closed'"
    )
    created_at: datetime = Field(
        description="Timestamp when the conversation was created"
    )
    updated_at: datetime = Field(
        description="Timestamp of the last message or status change"
    )


class RagConversationListResponse(BaseModel):
    """List wrapper for tenant-scoped RAG conversations."""

    conversations: list[RagConversationResponse] = Field(
        description="Conversations ordered newest-first"
    )


class RagConversationDetailResponse(BaseModel):
    """Conversation with stored messages."""

    conversation: RagConversationResponse = Field(description="Conversation metadata")
    messages: list[RagMessageResponse] = Field(
        description="All stored messages in turn order"
    )


class RagConversationMessageRequest(BaseModel):
    """Payload for sending one user message to a RAG conversation."""

    content: str = Field(
        min_length=1,
        max_length=8000,
        description="User message text to send to the persona",
    )


class RagConversationMessageResponse(BaseModel):
    """Response returned after one RAG chat turn."""

    user_message: RagMessageResponse = Field(
        description="Stored representation of the user turn"
    )
    assistant_message: RagMessageResponse = Field(
        description="Stored representation of the assistant turn"
    )
    citations: list[RagMessageCitationResponse] = Field(
        description="Retrieved chunks cited in the assistant response"
    )
    turns_remaining: int = Field(
        description="User turns remaining before the conversation limit is reached"
    )
