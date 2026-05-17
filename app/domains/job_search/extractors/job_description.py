"""Job description extractor for the Job Search domain pack."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.core.context_engine.models import Artifact, ArtifactChunk, ExtractionResult
from app.domains.job_search.extractors.common import (
    TECH_KEYWORDS,
    action,
    entity,
    infer_seniority,
    signal,
    signals_from_values,
)
from app.domains.job_search.models import (
    keyword_values,
    lines_containing,
    normalize_space,
    source_for_match,
)


@dataclass(frozen=True)
class JobDescriptionExtractor:
    """Extract role requirements, constraints, and risks from job descriptions."""

    id: str = "job-description-extractor"
    artifact_type_ids: tuple[str, ...] = ("job_description",)

    def extract(
        self,
        artifact: Artifact,
        chunks: list[ArtifactChunk],
    ) -> ExtractionResult:
        """Return generic context from one job description artifact."""
        if artifact.artifact_type_id != "job_description":
            return ExtractionResult()

        text = artifact.text
        entities = []
        signals = []
        actions = []

        title = self._extract_labeled_value(text, ["title", "role"])
        if title is None:
            title = self._role_like_heading(text)
        if title is not None:
            link = source_for_match(chunks, title, label="role title")
            entities.append(entity("role", title, link))
            signals.append(signal("role_title", "Role title", title, link))

        company = self._extract_labeled_value(text, ["company", "organization"])
        if company is not None:
            link = source_for_match(chunks, company, label="company")
            entities.append(entity("organization", company, link))
            signals.append(signal("company", "Company", company, link))

        seniority = infer_seniority(text)
        if seniority is not None:
            link = source_for_match(chunks, seniority.split("_")[0], label="seniority")
            signals.append(signal("seniority", "Seniority", seniority, link))

        responsibility_lines = lines_containing(
            chunks,
            [
                r"\b(responsib|own|build|lead|design|deliver|operate|manage)\b",
                r"^- ",
            ],
            label="responsibility",
        )[:8]
        signals.extend(
            signals_from_values(
                "responsibility",
                "Responsibility",
                responsibility_lines,
            )
        )

        technologies = keyword_values(chunks, TECH_KEYWORDS, label="technology")
        signals.extend(signals_from_values("technology", "Technology", technologies))
        entities.extend(
            entity("technology", item.value, item.source_link) for item in technologies
        )

        leadership = lines_containing(
            chunks,
            [
                r"\b(mentor|leadership|cross-functional|stakeholder|influence|strategy)\b"
            ],
            label="leadership expectation",
        )
        signals.extend(
            signals_from_values(
                "leadership_expectation",
                "Leadership expectation",
                leadership[:5],
            )
        )

        compensation = lines_containing(
            chunks,
            [r"\$[0-9]", r"\b(compensation|salary|equity|bonus|OTE|range)\b"],
            label="compensation",
        )
        signals.extend(
            signals_from_values("compensation", "Compensation signal", compensation[:5])
        )

        location = lines_containing(
            chunks,
            [r"\b(remote|hybrid|onsite|on-site|relocation|timezone|location)\b"],
            label="location constraint",
        )
        signals.extend(
            signals_from_values(
                "location_constraint",
                "Location constraint",
                location[:5],
            )
        )

        unusual_scope = lines_containing(
            chunks,
            [
                r"\b(0 to 1|zero to one|wear many hats|ambiguous|founding|greenfield)\b",
                r"\b(on-call|24/7|global|multiple teams|turnaround)\b",
            ],
            label="scope indicator",
        )
        signals.extend(
            signals_from_values(
                "unusual_scope_indicator",
                "Unusual scope indicator",
                unusual_scope[:5],
            )
        )

        if unusual_scope or len(responsibility_lines) >= 6:
            risk_source = (unusual_scope or leadership or responsibility_lines)[0]
            risk_text = "Role may have broad or ambiguous scope."
            signals.append(
                signal(
                    "inferred_risk",
                    "Inferred risk",
                    risk_text,
                    risk_source.source_link,
                    reason="scope_language",
                )
            )
            actions.append(
                action(
                    "clarify_scope",
                    "Clarify scope and success expectations",
                    risk_source.source_link,
                    description=(
                        "Ask what outcomes matter in the first 90 days and which "
                        "responsibilities are highest priority."
                    ),
                )
            )

        return ExtractionResult(
            entities=entities,
            signals=signals,
            actionable_items=actions,
            metadata={"artifact_type_id": artifact.artifact_type_id},
        )

    def _extract_labeled_value(self, text: str, labels: list[str]) -> str | None:
        for label in labels:
            match = re.search(
                rf"(?im)^\s*{re.escape(label)}\s*:\s*(.+)$",
                text,
            )
            if match is not None:
                return normalize_space(match.group(1))[:160]
        return None

    def _role_like_heading(self, text: str) -> str | None:
        for line in text.splitlines():
            cleaned = normalize_space(line)
            if (
                cleaned
                and len(cleaned) <= 120
                and not cleaned.lower().startswith(("http://", "https://", "www."))
                and re.search(
                    r"\b(engineer|developer|architect|manager|director|designer|analyst|lead)\b",
                    cleaned,
                    re.IGNORECASE,
                )
            ):
                return cleaned
        return None
