"""Typed experience registry for invite-scoped demo access."""

from __future__ import annotations

from enum import StrEnum


class ExperienceId(StrEnum):
    """Stable ids stored in invitation-code labels and access-token claims."""

    MESSY_NOTES = "messy-notes"
    RAG_DEMO = "rag-demo"
    VOICE_DEMO = "voice-demo"


EXPERIENCE_ROUTES: dict[ExperienceId, str] = {
    ExperienceId.MESSY_NOTES: "/messy-notes",
    ExperienceId.RAG_DEMO: "/rag-demo",
    ExperienceId.VOICE_DEMO: "/voice-demo",
}

EXPERIENCE_LABELS: dict[ExperienceId, str] = {
    ExperienceId.MESSY_NOTES: "Messy Notes",
    ExperienceId.RAG_DEMO: "RAG Demo",
    ExperienceId.VOICE_DEMO: "Voice Demo",
}

EXPERIENCE_DESCRIPTIONS: dict[ExperienceId, str] = {
    ExperienceId.MESSY_NOTES: (
        "Turn pasted text, text files, or extractable PDFs into a structured brief."
    ),
    ExperienceId.RAG_DEMO: (
        "A retrieval-grounded demo workspace with persona configuration and scoped document setup."
    ),
    ExperienceId.VOICE_DEMO: (
        "A real-time voice AI advisor that helps employers assess workforce development readiness."
    ),
}


def parse_experience_id(value: str | None) -> ExperienceId:
    """Parse an invitation label into a supported experience id."""
    if value is None:
        raise ValueError("Invitation code is not scoped to a supported experience.")
    try:
        return ExperienceId(value)
    except ValueError as exc:
        raise ValueError(
            "Invitation code is not scoped to a supported experience."
        ) from exc
