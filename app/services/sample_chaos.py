"""Curated sample inputs for the messy-notes demo."""

from __future__ import annotations

from fastapi import HTTPException, status

from app.schemas.runs import SampleChaosSet


_SAMPLES = [
    SampleChaosSet(
        key="product-planning",
        title="Product planning mess",
        description="Roadmap fragments, launch nerves, and one suspiciously calm spreadsheet.",
        notes=[
            "Decision: keep the first demo narrow, text-only, and actually shippable.",
            "Priya says onboarding needs sample data because nobody brings clean notes to a demo.",
            "Launch page says Q2. Calendar says Q3. Finance says please stop saying quarters.",
            "Need owner for the sample chaos button and empty-state copy.",
            "Customer quote maybe: 'This saves me from rereading my own meeting notes.' Verify before using.",
            "Legal asked whether uploaded PDFs are stored. Answer honestly: extracted text is persisted for the run.",
            "Do not add a general chat tab. It will look tempting. Resist the shiny door.",
            "Action: add one bounded follow-up after the brief, then close the loop.",
            "Roadmap maybe includes SMS later, but M6 only captures preference.",
        ],
    ),
    SampleChaosSet(
        key="research-synthesis",
        title="Research synthesis mess",
        description="Interview notes that mostly agree, except when they absolutely do not.",
        notes=[
            "User 3 wants fewer options and said the current flow feels like homework.",
            "User 5 asked for advanced controls, but only after seeing a fake advanced panel.",
            "Pattern: people trust the brief more when rejected inputs are visible.",
            "Contradiction: 'audit trail is too technical' vs 'please show exactly what happened.'",
            "Need to separate decisions from vibes. Vibes currently winning 7-3.",
            "Action for Marcos: pull two concise quotes, not the twelve-paragraph emotional journey.",
            "Risk: if sample notes are too polished, the demo feels staged.",
            "Observation: sticky notes made participants smile, then they immediately read the brief.",
        ],
    ),
    SampleChaosSet(
        key="strategy-notes",
        title="Strategy notes mess",
        description="Positioning, constraints, and a budget line that keeps reappearing.",
        notes=[
            "North star: practical AI tooling, not a chatbot in a blazer.",
            "Budget pressure: no paid registry, local build and ship to the VM.",
            "Decision: backend owns invite validation and signed tokens.",
            "Frontend owns browser rendering, localStorage token, and the protected demo slug.",
            "Concern: if backend admin routes leak through ingress, the architecture story collapses.",
            "Oracle compatibility matters. Postgres is convenient, not proof.",
            "Need a crisp explanation of config-driven tools/handoffs without pretending it is a giant platform.",
            "Follow-up model: one question about the generated brief, then boundaries return.",
        ],
    ),
    SampleChaosSet(
        key="mixed-life-meeting",
        title="Mixed meeting/personal/random notes",
        description="A realistic notebook where strategy and sandwich logistics briefly collide.",
        notes=[
            "Team retro: deploy docs are clearer, but rollback story still needs one clean sentence.",
            "Remember to text Sam the dentist recommendation. Not relevant unless Sam funds infrastructure.",
            "Decision: keep unsupported file states blunt and kind.",
            "Someone said OCR would be cool. Also someone said please do not build OCR this week.",
            "Action: ask Dana for the latest VM hostname before recording the demo.",
            "Risk: users paste giant docs and expect magic. We trim; we should say so.",
            "Lunch note: the good hummus place closes at 2:30.",
            "Open question: should completed runs show notification preference even before SMS exists?",
        ],
    ),
]


def list_sample_chaos_sets() -> list[SampleChaosSet]:
    """Return the curated sample catalog."""
    return _SAMPLES


def get_sample_chaos_set(sample_key: str) -> SampleChaosSet:
    """Return one curated sample set or raise a 404."""
    for sample in _SAMPLES:
        if sample.key == sample_key:
            return sample
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Sample chaos set not found.",
    )
