"""LLM-based greeting synthesis for voice experience configurations."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.voice import VoiceExperienceConfig, VoicePersona

logger = logging.getLogger(__name__)

_SYNTHESIS_SYSTEM_PROMPT = (
    "You write short, natural voice greetings for an AI phone advisor. "
    "The greeting must be one or two sentences. "
    "It should state the advisor's name, briefly mention what help is available, "
    "and end with an open question. "
    "Do not use bullet points, markdown, or any formatting. "
    "Write as spoken words only."
)

_SINGLE_PERSONA_PROMPT = (
    "Write a greeting for a voice advisor named {voice_name}. "
    "Capabilities: {capabilities}"
)

_MULTI_PERSONA_PROMPT = (
    "Write a greeting for a voice advisor named {voice_name}. "
    "It can help with multiple things: {capabilities_list}"
)


def synthesize_greeting(
    config: VoiceExperienceConfig,
    active_personas: list[VoicePersona],
    settings: Settings,
) -> str:
    """Use an LLM to generate a natural greeting from active personas' capabilities.

    Returns the synthesized greeting text, or a safe fallback if synthesis fails.
    """
    if not active_personas:
        return f"Hi, I'm {config.voice_name}. How can I help you today?"

    capabilities_parts = [p.capabilities_serialized or p.name for p in active_personas]

    if len(active_personas) == 1:
        user_prompt = _SINGLE_PERSONA_PROMPT.format(
            voice_name=config.voice_name,
            capabilities=capabilities_parts[0],
        )
    else:
        capabilities_list = "; ".join(capabilities_parts)
        user_prompt = _MULTI_PERSONA_PROMPT.format(
            voice_name=config.voice_name,
            capabilities_list=capabilities_list,
        )

    try:
        return _call_llm(user_prompt, settings)
    except Exception:
        logger.exception(
            "Greeting synthesis failed for experience %s; using fallback",
            config.experience_id,
        )
        return _fallback_greeting(config, active_personas)


def _call_llm(user_prompt: str, settings: Settings) -> str:
    provider = settings.voice_greeting_provider
    model = settings.voice_greeting_model

    if provider == "openai":
        return _openai_complete(user_prompt, model, settings)
    if provider == "anthropic":
        return _anthropic_complete(user_prompt, model, settings)

    raise ValueError(f"Unsupported voice greeting provider: {provider}")


def _openai_complete(prompt: str, model: str, settings: Settings) -> str:
    from openai import OpenAI

    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY required for voice greeting synthesis")

    client = OpenAI(api_key=settings.openai_api_key)
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": _SYNTHESIS_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        max_tokens=120,
        temperature=0.7,
    )
    content = response.choices[0].message.content
    return (content or "").strip()


def _anthropic_complete(prompt: str, model: str, settings: Settings) -> str:
    from anthropic import Anthropic

    if not settings.anthropic_api_key:
        raise ValueError("ANTHROPIC_API_KEY required for voice greeting synthesis")

    client = Anthropic(api_key=settings.anthropic_api_key)
    response = client.messages.create(
        model=model,
        system=_SYNTHESIS_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=120,
    )
    block = response.content[0]
    return getattr(block, "text", "").strip()


def _fallback_greeting(
    config: VoiceExperienceConfig, personas: list[VoicePersona]
) -> str:
    names = [p.name for p in personas]
    if len(names) == 1:
        return (
            f"Hi, I'm {config.voice_name}. I can help with {names[0]}. "
            "What can I help you with today?"
        )
    listed = ", ".join(names[:-1]) + f", or {names[-1]}"
    return (
        f"Hi, I'm {config.voice_name}. I can help with {listed}. "
        "What are you looking for today?"
    )


def refresh_greeting_if_needed(
    db: Session,
    experience_id: str,
    settings: Settings,
) -> None:
    """Synthesize and persist a new greeting for the experience.

    Called as a background task after any persona change.
    """
    config = (
        db.query(VoiceExperienceConfig)
        .filter(VoiceExperienceConfig.experience_id == experience_id)
        .first()
    )
    if config is None:
        # Auto-create a minimal config so the greeting can be synthesized
        # without requiring the operator to save the voice name first.
        config = VoiceExperienceConfig(
            experience_id=experience_id,
            voice_name="Assistant",
        )
        db.add(config)
        db.flush()
        logger.info(
            "Auto-created VoiceExperienceConfig for %s with default voice name",
            experience_id,
        )

    active_personas = (
        db.query(VoicePersona)
        .filter(
            VoicePersona.experience_id == experience_id,
            VoicePersona.is_active.is_(True),
        )
        .all()
    )

    greeting = synthesize_greeting(config, active_personas, settings)
    config.synthesized_greeting = greeting
    config.greeting_synced_at = datetime.now(UTC)
    db.commit()
    logger.info(
        "Greeting refreshed for experience %s (%d active personas)",
        experience_id,
        len(active_personas),
    )
