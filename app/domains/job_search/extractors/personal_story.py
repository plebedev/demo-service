"""Personal story extractor for the Job Search domain pack."""

from __future__ import annotations

from dataclasses import dataclass

from app.core.context_engine.models import Artifact, ArtifactChunk, ExtractionResult
from app.domains.job_search.extractors.common import signals_from_values
from app.domains.job_search.models import lines_containing


@dataclass(frozen=True)
class PersonalStoryExtractor:
    """Extract structured story evidence from personal career stories."""

    id: str = "personal-story-extractor"
    artifact_type_ids: tuple[str, ...] = ("personal_story",)

    def extract(
        self,
        artifact: Artifact,
        chunks: list[ArtifactChunk],
    ) -> ExtractionResult:
        """Return generic context from one personal-story artifact."""
        if artifact.artifact_type_id != "personal_story":
            return ExtractionResult()

        situations = lines_containing(
            chunks,
            [r"\b(situation|context|challenge|problem|when|at the time)\b"],
            label="story situation",
        )[:5]
        actions = lines_containing(
            chunks,
            [r"\b(i led|i built|i designed|i created|action|approach|we built)\b"],
            label="story action",
        )[:5]
        results = lines_containing(
            chunks,
            [r"\b(result|outcome|impact|improved|reduced|increased|launched|saved)\b"],
            label="story result",
        )[:5]
        competencies = lines_containing(
            chunks,
            [r"\b(ownership|collaboration|communication|judgment|execution)\b"],
            label="competency",
        )[:5]
        leadership = lines_containing(
            chunks,
            [r"\b(led|mentored|aligned|stakeholder|strategy|influence)\b"],
            label="leadership theme",
        )[:5]
        technical = lines_containing(
            chunks,
            [r"\b(api|system|platform|data|cloud|kubernetes|python|typescript|ai)\b"],
            label="technical theme",
        )[:5]

        signals = []
        signals.extend(signals_from_values("story_situation", "Situation", situations))
        signals.extend(signals_from_values("story_action", "Action", actions))
        signals.extend(signals_from_values("story_result", "Result", results))
        signals.extend(
            signals_from_values(
                "relevant_competency", "Relevant competency", competencies
            )
        )
        signals.extend(
            signals_from_values("leadership_theme", "Leadership theme", leadership)
        )
        signals.extend(
            signals_from_values("technical_theme", "Technical theme", technical)
        )
        return ExtractionResult(
            signals=signals,
            metadata={"artifact_type_id": artifact.artifact_type_id},
        )
