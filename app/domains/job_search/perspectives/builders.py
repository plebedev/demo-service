"""Perspective builders for the Job Search domain pack."""

from __future__ import annotations

from dataclasses import dataclass

from app.core.context_engine.models import (
    ContextSignal,
    EvidenceLink,
    PerspectiveBuildContext,
    PerspectiveView,
    SourceLink,
    ViewSection,
)


def _signals(context: PerspectiveBuildContext, *types: str) -> list[ContextSignal]:
    type_set = set(types)
    return [signal for signal in context.signals if signal.signal_type in type_set]


def _content(signals: list[ContextSignal], empty: str) -> str:
    if not signals:
        return empty
    values = [str(signal.value or signal.label) for signal in signals[:8]]
    return "\n".join(f"- {value}" for value in values)


def _evidence(signals: list[ContextSignal]) -> list[EvidenceLink]:
    links: list[EvidenceLink] = []
    for signal in signals[:8]:
        for source in signal.source_links[:1]:
            evidence_kind = (
                "inferred"
                if signal.signal_type.startswith("inferred")
                or signal.metadata.get("reason") is not None
                else "explicit"
            )
            links.append(
                EvidenceLink(
                    source=source,
                    note=f"{signal.label} ({evidence_kind})",
                )
            )
    return links


def _section(
    section_id: str,
    title: str,
    signals: list[ContextSignal],
    empty: str,
) -> ViewSection:
    return ViewSection(
        id=section_id,
        title=title,
        content=_content(signals, empty),
        evidence_links=_evidence(signals),
        metadata={
            "signal_types": sorted({signal.signal_type for signal in signals}),
            "evidence_kinds": sorted(
                {
                    (
                        "inferred"
                        if signal.signal_type.startswith("inferred")
                        or signal.metadata.get("reason") is not None
                        else "explicit"
                    )
                    for signal in signals
                }
            ),
        },
    )


def _task_section(
    context: PerspectiveBuildContext,
    section_id: str,
    title: str,
    item_types: set[str],
    empty: str,
) -> ViewSection:
    items = [item for item in context.actionable_items if item.item_type in item_types]
    content = "\n".join(f"- {item.title}" for item in items[:8]) if items else empty
    evidence: list[EvidenceLink] = []
    for item in items[:8]:
        evidence.extend(
            EvidenceLink(source=link, note=item.title) for link in item.source_links[:1]
        )
    return ViewSection(
        id=section_id,
        title=title,
        content=content,
        evidence_links=evidence,
        metadata={
            "item_types": sorted(item_types),
            "readiness_statuses": sorted(
                {item.readiness_status.value for item in items}
            ),
        },
    )


def _manual_section(
    section_id: str, title: str, text: str, source: SourceLink | None
) -> ViewSection:
    evidence = [EvidenceLink(source=source)] if source is not None else []
    return ViewSection(
        id=section_id,
        title=title,
        content=text,
        evidence_links=evidence,
        metadata={"evidence_kinds": ["human_judgment"]},
    )


@dataclass(frozen=True)
class RoleFitPerspectiveBuilder:
    """Build the role-fit perspective."""

    id: str = "role_fit"

    def build(self, context: PerspectiveBuildContext) -> PerspectiveView:
        """Build role-fit sections from source-grounded context signals."""
        tech_matches = _signals(
            context, "technology", "technical_skill", "platform_experience"
        )
        risks = _signals(context, "inferred_risk", "unusual_scope_indicator")
        missing = _signals(context, "open_question", "interviewer_concern")
        positioning = _signals(
            context,
            "leadership_signal",
            "measurable_outcome",
            "ai_agent_experience",
            "role_experience",
        )
        return PerspectiveView(
            view_definition_id=self.id,
            title="Role Fit",
            sections=[
                _section(
                    "strong_matches",
                    "Strong Matches",
                    tech_matches,
                    "No strong matches yet.",
                ),
                _section(
                    "weak_or_missing",
                    "Weak or Missing Evidence",
                    missing,
                    "No missing-evidence signals yet.",
                ),
                _section("risks", "Risks", risks, "No role-fit risks extracted yet."),
                _section(
                    "positioning",
                    "Suggested Positioning",
                    positioning,
                    "Add resume or story evidence to generate positioning.",
                ),
                _section(
                    "open_questions",
                    "Open Questions",
                    _signals(
                        context,
                        "open_question",
                        "location_constraint",
                        "company_signal",
                    ),
                    "No open questions captured yet.",
                ),
            ],
        )


@dataclass(frozen=True)
class InterviewPrepPerspectiveBuilder:
    """Build the interview-prep perspective."""

    id: str = "interview_prep"

    def build(self, context: PerspectiveBuildContext) -> PerspectiveView:
        """Build interview-prep sections from extracted themes and stories."""
        return PerspectiveView(
            view_definition_id=self.id,
            title="Interview Prep",
            sections=[
                _section(
                    "themes",
                    "Likely Interview Themes",
                    _signals(
                        context,
                        "technical_theme",
                        "leadership_expectation",
                        "company_signal",
                    ),
                    "No interview themes yet.",
                ),
                _section(
                    "stories",
                    "Best Supporting Stories",
                    _signals(
                        context, "story_situation", "story_action", "story_result"
                    ),
                    "Add personal stories to ground this section.",
                ),
                _section(
                    "technical",
                    "Technical Topics",
                    _signals(
                        context, "technology", "technical_skill", "platform_experience"
                    ),
                    "No technical topics extracted yet.",
                ),
                _section(
                    "questions",
                    "Questions To Ask",
                    _signals(
                        context, "open_question", "location_constraint", "compensation"
                    ),
                    "No questions suggested yet.",
                ),
                _section(
                    "concerns",
                    "Concerns To Clarify",
                    _signals(
                        context,
                        "interviewer_concern",
                        "interview_risk",
                        "inferred_risk",
                        "company_signal",
                    ),
                    "No concerns captured yet.",
                ),
            ],
        )


@dataclass(frozen=True)
class ResumePositioningPerspectiveBuilder:
    """Build the resume-positioning perspective."""

    id: str = "resume_positioning"

    def build(self, context: PerspectiveBuildContext) -> PerspectiveView:
        """Build resume-positioning sections from role and resume evidence."""
        return PerspectiveView(
            view_definition_id=self.id,
            title="Resume Positioning",
            sections=[
                _section(
                    "strong_resume",
                    "Strong Resume Areas",
                    _signals(
                        context,
                        "measurable_outcome",
                        "technical_skill",
                        "leadership_signal",
                    ),
                    "No strong resume areas extracted yet.",
                ),
                _section(
                    "missing",
                    "Missing Evidence",
                    _signals(context, "responsibility", "leadership_expectation"),
                    "No missing evidence inferred yet.",
                ),
                _section(
                    "weak",
                    "Weak Positioning",
                    _signals(context, "interviewer_concern", "interview_risk"),
                    "No weak positioning signals yet.",
                ),
                _task_section(
                    context,
                    "rewrites",
                    "Suggested Rewrites",
                    {"rewrite_resume_section"},
                    "No rewrite tasks generated yet.",
                ),
            ],
        )


@dataclass(frozen=True)
class ApplicationPipelinePerspectiveBuilder:
    """Build the application-pipeline perspective."""

    id: str = "application_pipeline"

    def build(self, context: PerspectiveBuildContext) -> PerspectiveView:
        """Build application-pipeline sections from opportunities and tasks."""
        opportunities = _signals(context, "company", "role_title")
        blockers = _signals(context, "interview_risk", "inferred_risk")
        return PerspectiveView(
            view_definition_id=self.id,
            title="Application Pipeline",
            sections=[
                _section(
                    "active",
                    "Active Opportunities",
                    opportunities,
                    "No active opportunities ingested yet.",
                ),
                _task_section(
                    context,
                    "next",
                    "Next Actions",
                    {
                        "prepare_interview_brief",
                        "draft_recruiter_follow_up",
                        "research_company_concerns",
                    },
                    "No next actions generated yet.",
                ),
                _section(
                    "blockers", "Blockers", blockers, "No blockers extracted yet."
                ),
                _task_section(
                    context,
                    "followups",
                    "Follow-Ups",
                    {
                        "draft_recruiter_follow_up",
                        "clarify_compensation_expectations",
                        "clarify_scope",
                        "prepare_architecture_story",
                    },
                    "No follow-up tasks generated yet.",
                ),
            ],
        )


@dataclass(frozen=True)
class CompensationScopeRiskPerspectiveBuilder:
    """Build the compensation/scope risk perspective."""

    id: str = "compensation_scope_risk"

    def build(self, context: PerspectiveBuildContext) -> PerspectiveView:
        """Build compensation and scope-risk sections."""
        title_signals = _signals(context, "role_title", "seniority")
        human_source = (
            context.signals[0].source_links[0]
            if context.signals and context.signals[0].source_links
            else None
        )
        return PerspectiveView(
            view_definition_id=self.id,
            title="Compensation and Scope Risk",
            sections=[
                _section(
                    "comp",
                    "Compensation Signals",
                    _signals(context, "compensation"),
                    "No compensation signals yet.",
                ),
                _section(
                    "scope",
                    "Scope Risks",
                    _signals(context, "unusual_scope_indicator", "inferred_risk"),
                    "No scope risks extracted yet.",
                ),
                _section(
                    "title",
                    "Title Concerns",
                    title_signals,
                    "No title concerns extracted yet.",
                ),
                _manual_section(
                    "judgment",
                    "Human Judgment Areas",
                    "Use these signals as prompts for human judgment; the demo does not decide compensation fairness or career fit automatically.",
                    human_source,
                ),
            ],
        )
