"""Supplemental extractors for career-context notes."""

from __future__ import annotations

from dataclasses import dataclass

from app.core.context_engine.models import Artifact, ArtifactChunk, ExtractionResult
from app.domains.job_search.extractors.common import signal, signals_from_values
from app.domains.job_search.models import lines_containing, source_for_match


@dataclass(frozen=True)
class CareerContextNotesExtractor:
    """Extract useful signals from non-canonical career artifacts."""

    id: str = "career-context-notes-extractor"
    artifact_type_ids: tuple[str, ...] = (
        "recruiter_message",
        "company_research",
        "compensation_notes",
        "follow_up_notes",
    )

    def extract(
        self,
        artifact: Artifact,
        chunks: list[ArtifactChunk],
    ) -> ExtractionResult:
        """Return source-grounded context from career notes."""
        if artifact.artifact_type_id not in self.artifact_type_ids:
            return ExtractionResult()

        signals = []
        if artifact.artifact_type_id == "recruiter_message":
            signals.extend(
                signals_from_values(
                    "open_question",
                    "Recruiter question",
                    lines_containing(
                        chunks,
                        [r"\?", r"\b(available|interest|timeline|process)\b"],
                        label="recruiter question",
                    )[:6],
                )
            )
            signals.extend(
                signals_from_values(
                    "compensation",
                    "Compensation mention",
                    lines_containing(
                        chunks,
                        [r"\$[0-9]", r"\b(comp|salary|range|equity|bonus|ote)\b"],
                        label="compensation",
                    )[:6],
                )
            )
            signals.extend(
                signals_from_values(
                    "location_constraint",
                    "Location/process constraint",
                    lines_containing(
                        chunks,
                        [r"\b(remote|hybrid|onsite|relocat|timezone|process|round)\b"],
                        label="location/process",
                    )[:6],
                )
            )

        if artifact.artifact_type_id == "company_research":
            signals.extend(
                signals_from_values(
                    "company_signal",
                    "Company signal",
                    lines_containing(
                        chunks,
                        [
                            r"\b(market|customer|product|funding|revenue|team|strategy)\b"
                        ],
                        label="company signal",
                    )[:8],
                )
            )
            concerns = lines_containing(
                chunks,
                [r"\b(risk|concern|layoff|runway|competition|unclear|weak)\b"],
                label="company concern",
            )[:6]
            signals.extend(
                signals_from_values("inferred_risk", "Company concern", concerns)
            )

        if artifact.artifact_type_id == "compensation_notes":
            signals.extend(
                signals_from_values(
                    "compensation",
                    "Compensation signal",
                    lines_containing(
                        chunks,
                        [r"\$[0-9]", r"\b(base|bonus|equity|salary|range|ote)\b"],
                        label="compensation",
                    )[:8],
                )
            )
            signals.extend(
                signals_from_values(
                    "open_question",
                    "Compensation question",
                    lines_containing(
                        chunks,
                        [r"\?", r"\b(clarify|decide|minimum|target|tradeoff)\b"],
                        label="compensation question",
                    )[:6],
                )
            )

        if artifact.artifact_type_id == "follow_up_notes":
            signals.extend(
                signals_from_values(
                    "next_action_signal",
                    "Follow-up signal",
                    lines_containing(
                        chunks,
                        [r"\b(send|follow up|reply|thank|schedule|prepare|next)\b"],
                        label="follow-up",
                    )[:8],
                )
            )
            signals.extend(
                signals_from_values(
                    "open_question",
                    "Follow-up question",
                    lines_containing(
                        chunks, [r"\?", r"\b(ask|clarify)\b"], label="question"
                    )[:6],
                )
            )

        if not signals and chunks:
            first = chunks[0].text[:160]
            signals.append(
                signal(
                    "source_summary",
                    "Source summary",
                    first,
                    source_for_match(
                        chunks, first[:40], label=artifact.artifact_type_id
                    ),
                )
            )

        return ExtractionResult(
            signals=signals,
            metadata={"artifact_type_id": artifact.artifact_type_id},
        )
