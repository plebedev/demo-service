"""Guarded one-question follow-up support for completed runs."""

from __future__ import annotations

from typing import Any, cast

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.run import Run, RunStatus
from app.schemas.runs import FollowUpRequest, FollowUpResponse


_ALLOWED_MARKERS = {
    "contradiction": "contradiction",
    "contradict": "contradiction",
    "decision": "decisions",
    "decisions": "decisions",
    "risk": "risks",
    "risks": "risks",
    "explain": "explain",
    "clarify": "clarify",
    "question": "open_questions",
    "questions": "open_questions",
    "summary": "summary",
    "summarize": "summary",
}


def answer_follow_up(db: Session, run: Run, payload: FollowUpRequest) -> Run:
    """Answer exactly one bounded follow-up about the generated brief."""
    if run.status != RunStatus.COMPLETED.value or not run.output_brief_serialized:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Follow-up is available only after a brief is complete.",
        )
    if run.follow_up_count >= 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This run already used its one follow-up question.",
        )

    category = _classify_question(payload.question)
    if category is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Follow-up must stay about this brief: ask about decisions, risks, "
                "contradictions, open questions, or one point that needs explaining."
            ),
        )

    from app.services.runs import _deserialize_json_object, _serialize_model

    brief = _deserialize_json_object(run.output_brief_serialized) or {}
    response = FollowUpResponse(
        question=payload.question.strip(),
        answer=_build_answer(category, brief),
        category=category,
    )
    run.follow_up_count = 1
    run.follow_up_response_serialized = cast(Any, _serialize_model(response))
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def _classify_question(question: str) -> str | None:
    lowered = question.lower()
    if any(
        marker in lowered
        for marker in ("weather", "joke", "recipe", "email", "code", "write me")
    ):
        return None
    for marker, category in _ALLOWED_MARKERS.items():
        if marker in lowered:
            return category
    if "?" in question and any(
        marker in lowered for marker in ("brief", "point", "mean", "why")
    ):
        return "explain"
    return None


def _build_answer(category: str, brief: dict[str, object]) -> str:
    if category == "summary":
        return str(
            brief.get("executive_summary")
            or "The brief did not include enough summary detail to compress further."
        )
    if category == "decisions":
        return _section_answer(
            brief,
            "Decisions",
            "The brief did not find explicit decisions in the notes.",
        )
    if category == "risks":
        questions = _list_answer(brief.get("open_questions"))
        if questions:
            return f"The main risk is unresolved confidence: {questions}"
        return "No explicit risks were surfaced beyond verifying the brief before acting on it."
    if category == "contradiction":
        questions = _list_answer(brief.get("open_questions"))
        if questions:
            return f"The brief flags this tension to resolve: {questions}"
        return "No contradiction was explicit enough for the workflow to flag."
    if category == "open_questions":
        questions = _list_answer(brief.get("open_questions"))
        return questions or "No open questions were stored on this brief."
    return (
        "The safest reading is to stay grounded in the generated sections: "
        f"{_first_section(brief)}"
    )


def _section_answer(brief: dict[str, object], heading: str, fallback: str) -> str:
    sections = brief.get("sections")
    if not isinstance(sections, list):
        return fallback
    for section in sections:
        if not isinstance(section, dict):
            continue
        if str(section.get("heading", "")).lower() == heading.lower():
            content = str(section.get("content") or "").strip()
            return content or fallback
    return fallback


def _first_section(brief: dict[str, object]) -> str:
    sections = brief.get("sections")
    if isinstance(sections, list) and sections and isinstance(sections[0], dict):
        return str(sections[0].get("content") or "the brief has sparse detail.")
    return "the brief has sparse detail."


def _list_answer(value: object) -> str:
    if not isinstance(value, list):
        return ""
    return " ".join(str(item) for item in value if str(item).strip())
