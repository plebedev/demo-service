"""Interview notes extractor for the Job Search domain pack."""

from __future__ import annotations

from dataclasses import dataclass

from app.core.context_engine.models import Artifact, ArtifactChunk, ExtractionResult
from app.domains.job_search.extractors.common import action, signals_from_values
from app.domains.job_search.models import lines_containing


@dataclass(frozen=True)
class InterviewNotesExtractor:
    """Extract concerns, themes, risks, and follow-ups from interview notes."""

    id: str = "interview-notes-extractor"
    artifact_type_ids: tuple[str, ...] = ("interview_notes",)

    def extract(
        self,
        artifact: Artifact,
        chunks: list[ArtifactChunk],
    ) -> ExtractionResult:
        """Return generic context from one interview-notes artifact."""
        if artifact.artifact_type_id != "interview_notes":
            return ExtractionResult()

        concerns = lines_containing(
            chunks,
            [r"\b(concern|worried|gap|unclear|hesitat|pushback)\b"],
            label="interviewer concern",
        )[:8]
        questions = lines_containing(
            chunks,
            [r"\?|open question|need to know|clarify"],
            label="open question",
        )[:8]
        themes = lines_containing(
            chunks,
            [r"\b(system design|architecture|scale|data|api|frontend|backend|cloud)\b"],
            label="technical theme",
        )[:8]
        risks = lines_containing(
            chunks,
            [r"\b(risk|blocker|weak|missing|not enough|scope|title)\b"],
            label="interview risk",
        )[:8]
        next_actions = lines_containing(
            chunks,
            [r"\b(next|follow up|send|prepare|study|draft|schedule)\b"],
            label="next action",
        )[:8]

        signals = []
        signals.extend(
            signals_from_values("interviewer_concern", "Interviewer concern", concerns)
        )
        signals.extend(signals_from_values("open_question", "Open question", questions))
        signals.extend(
            signals_from_values("technical_theme", "Technical theme", themes)
        )
        signals.extend(signals_from_values("interview_risk", "Interview risk", risks))
        signals.extend(
            signals_from_values("next_action_signal", "Next action", next_actions)
        )

        actions = [
            action(
                "clarify_interviewer_concern",
                "Clarify interviewer concern",
                item.source_link,
                description=item.value,
            )
            for item in concerns[:3]
        ]
        actions.extend(
            action(
                "prepare_technical_study_plan",
                "Prepare technical study plan",
                item.source_link,
                description=item.value,
            )
            for item in themes[:3]
        )

        return ExtractionResult(
            signals=signals,
            actionable_items=actions,
            metadata={"artifact_type_id": artifact.artifact_type_id},
        )
