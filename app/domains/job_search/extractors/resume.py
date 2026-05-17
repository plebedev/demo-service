"""Resume extractor for the Job Search domain pack."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.core.context_engine.models import Artifact, ArtifactChunk, ExtractionResult
from app.domains.job_search.extractors.common import (
    TECH_KEYWORDS,
    entity,
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
class ResumeExtractor:
    """Extract source-grounded career evidence from resumes."""

    id: str = "resume-extractor"
    artifact_type_ids: tuple[str, ...] = ("resume",)

    def extract(
        self,
        artifact: Artifact,
        chunks: list[ArtifactChunk],
    ) -> ExtractionResult:
        """Return generic context from one resume artifact."""
        if artifact.artifact_type_id != "resume":
            return ExtractionResult()

        entities = []
        signals = []

        role_lines = lines_containing(
            chunks,
            [r"\b(engineer|developer|architect|manager|director|lead|founder)\b"],
            label="resume role",
        )[:10]
        for item in role_lines:
            signals.append(
                signal(
                    "role_experience", "Role experience", item.value, item.source_link
                )
            )
            possible_company = self._company_from_role_line(item.value)
            if possible_company is not None:
                entities.append(
                    entity("organization", possible_company, item.source_link)
                )

        technologies = keyword_values(chunks, TECH_KEYWORDS, label="technical skill")
        signals.extend(
            signals_from_values("technical_skill", "Technical skill", technologies)
        )
        entities.extend(
            entity("technology", item.value, item.source_link) for item in technologies
        )

        platform = lines_containing(
            chunks,
            [
                r"\b(platform|infrastructure|kubernetes|terraform|cloud|oracle|postgres)\b"
            ],
            label="platform experience",
        )[:8]
        signals.extend(
            signals_from_values(
                "platform_experience",
                "Infrastructure/platform experience",
                platform,
            )
        )

        ai_agent = lines_containing(
            chunks,
            [r"\b(ai|agent|rag|llm|embedding|openai|anthropic|prompt)\b"],
            label="ai experience",
        )[:8]
        signals.extend(
            signals_from_values("ai_agent_experience", "AI/agent experience", ai_agent)
        )

        outcomes = lines_containing(
            chunks,
            [r"\b[0-9]+%|\$[0-9]|\b(increased|reduced|saved|grew|launched|improved)\b"],
            label="measurable outcome",
        )[:10]
        signals.extend(
            signals_from_values("measurable_outcome", "Measurable outcome", outcomes)
        )

        leadership = lines_containing(
            chunks,
            [r"\b(led|mentored|managed|hired|strategy|stakeholder|cross-functional)\b"],
            label="leadership signal",
        )[:10]
        signals.extend(
            signals_from_values("leadership_signal", "Leadership signal", leadership)
        )

        companies = self._companies_from_text(artifact.text)
        for company in companies[:8]:
            link = source_for_match(chunks, company, label="company")
            entities.append(entity("organization", company, link))
            signals.append(signal("company_experience", "Company", company, link))

        return ExtractionResult(
            entities=entities,
            signals=signals,
            metadata={"artifact_type_id": artifact.artifact_type_id},
        )

    def _company_from_role_line(self, line: str) -> str | None:
        if " at " in line:
            return normalize_space(line.split(" at ", 1)[1])[:120]
        if " - " in line:
            return normalize_space(line.split(" - ", 1)[0])[:120]
        return None

    def _companies_from_text(self, text: str) -> list[str]:
        companies: list[str] = []
        seen: set[str] = set()
        for match in re.finditer(r"(?m)^([A-Z][A-Za-z0-9&., ]{2,60})\s+[|—-]", text):
            company = normalize_space(match.group(1))
            if company.lower() not in seen:
                seen.add(company.lower())
                companies.append(company)
        return companies
