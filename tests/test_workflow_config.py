"""Tests for workflow YAML loading, registries, and event scaffolding."""

from __future__ import annotations

from pathlib import Path
import asyncio
from dataclasses import replace

import pytest

from sqlalchemy import text

from app.core.config import Settings
from app.db.models import Run, RunEvent
from app.services.model_factory import (
    create_model_settings,
    create_provider_model_settings,
    required_api_key_env_var,
)
from app.services.run_events import record_run_event, serialize_run_event
from app.services.runs import create_run
from app.services.tool_registry import (
    ToolCategory,
    ToolRegistry,
    build_tool_registry,
)
from app.services.workflow_executor import WorkflowExecutionError, execute_run_workflow
from app.schemas.run_events import RunEventPayload
from app.schemas.runs import RunCreateRequest
from app.workflows.config_models import (
    AgentWorkflowConfig,
    PostProcessorCatalog,
    WorkflowConfig,
    WorkflowProvider,
)
from app.workflows.loader import (
    assemble_system_prompt,
    load_workflow_registry,
)
from app.models.run_event import RunEventType
from app.workflows.tools import SectionsInput, TextToolInput


def build_settings(
    tmp_path: Path,
    *,
    workflow_dir: Path | None = None,
    post_processors_path: Path | None = None,
) -> Settings:
    """Build a settings object pointing at test config assets."""
    return Settings.model_validate(
        {
            "APP_NAME": "Backend API",
            "ENVIRONMENT": "test",
            "DATABASE_URL": "postgresql+psycopg://demo_service:demo_service@127.0.0.1:5432/demo_service",
            "ADMIN_API_SECRET": "test-admin-secret",
            "ACCESS_TOKEN_SIGNING_KEY": "test-signing-key",
            "OPENAI_API_KEY": "test-openai-key",
            "ANTHROPIC_API_KEY": "test-anthropic-key",
            "WORKFLOW_CONFIG_DIR": str(
                workflow_dir
                or Path(
                    "/Users/plebedev/github/demo/demo-service/app/resources/workflows"
                )
            ),
            "POST_PROCESSOR_CONFIG_PATH": str(
                post_processors_path
                or Path(
                    "/Users/plebedev/github/demo/demo-service/app/resources/post_processors/post-processors.yaml"
                )
            ),
            "DEFAULT_WORKFLOW_KEY": "messy-notes-v1",
        }
    )


def test_valid_workflow_yaml_loads_successfully(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    registry = load_workflow_registry(settings)

    workflow = registry.get_workflow("messy-notes-v1")
    assert workflow.config.starting_agent == "orchestrator"
    assert workflow.agents["extractor"].config.parallel is not None
    assert "audit-tool-usage-and-handoffs" in registry.post_processors


def test_invalid_workflow_yaml_fails_clearly(tmp_path: Path) -> None:
    workflow_dir = tmp_path / "workflows"
    workflow_dir.mkdir()
    (workflow_dir / "bad.yaml").write_text(
        "key: broken\nstarting_agent: orchestrator\nagents: []\n",
        encoding="utf-8",
    )
    post_processors_path = tmp_path / "post-processors.yaml"
    post_processors_path.write_text(
        "post_processors:\n  - key: audit-tool-usage-and-handoffs\n    type: audit_tool_usage_and_handoffs\n    description: ok\n    provider: anthropic\n    model: claude-3-5-haiku-latest\n    system_prompt: prompt\n    prompt_template: template\n",
        encoding="utf-8",
    )

    settings = build_settings(
        tmp_path,
        workflow_dir=workflow_dir,
        post_processors_path=post_processors_path,
    )

    with pytest.raises(ValueError, match="Invalid configuration"):
        load_workflow_registry(settings)


def test_missing_handoff_target_fails_validation() -> None:
    with pytest.raises(ValueError, match="unknown handoff targets"):
        WorkflowConfig.model_validate(
            {
                "key": "bad-handoff",
                "description": "broken",
                "starting_agent": "orchestrator",
                "agents": [
                    {
                        "role": "orchestrator",
                        "provider": "openai",
                        "model": "gpt-5-mini",
                        "system_prompt": "prompt",
                        "tools": [],
                        "can_handoff_to": ["missing-agent"],
                    }
                ],
            }
        )


def test_missing_referenced_post_processor_fails_validation(tmp_path: Path) -> None:
    workflow_dir = tmp_path / "workflows"
    workflow_dir.mkdir()
    (workflow_dir / "missing-post.yaml").write_text(
        "\n".join(
            [
                "key: test-workflow",
                "description: test",
                "starting_agent: orchestrator",
                "post_processors:",
                "  - missing-post",
                "agents:",
                "  - role: orchestrator",
                "    provider: openai",
                "    model: gpt-5-mini",
                "    system_prompt: prompt",
                "    tools: []",
                "    can_handoff_to: []",
            ]
        ),
        encoding="utf-8",
    )
    post_processors_path = tmp_path / "post-processors.yaml"
    post_processors_path.write_text(
        "post_processors:\n  - key: known-post\n    type: audit_tool_usage_and_handoffs\n    description: ok\n    provider: anthropic\n    model: claude-3-5-haiku-latest\n    system_prompt: prompt\n    prompt_template: template\n",
        encoding="utf-8",
    )

    settings = build_settings(
        tmp_path,
        workflow_dir=workflow_dir,
        post_processors_path=post_processors_path,
    )

    with pytest.raises(ValueError, match="unknown post-processors"):
        load_workflow_registry(settings)


def test_duplicate_agent_roles_fail_validation() -> None:
    with pytest.raises(ValueError, match="duplicate agent roles"):
        WorkflowConfig.model_validate(
            {
                "key": "dupe-roles",
                "description": "broken",
                "starting_agent": "orchestrator",
                "agents": [
                    {
                        "role": "orchestrator",
                        "provider": "openai",
                        "model": "gpt-5-mini",
                        "system_prompt": "prompt",
                        "tools": [],
                        "can_handoff_to": [],
                    },
                    {
                        "role": "orchestrator",
                        "provider": "anthropic",
                        "model": "claude-3-5-haiku-latest",
                        "system_prompt": "prompt",
                        "tools": [],
                        "can_handoff_to": [],
                    },
                ],
            }
        )


def test_tool_registry_lookup_and_prompt_assembly() -> None:
    registry = build_tool_registry()

    load_tool = registry.get("load_run_context")
    assert load_tool.name == "load_run_context"

    prompt = assemble_system_prompt(
        "Base system prompt.",
        registry,
        ["load_run_context", "persist_brief_draft"],
    )
    assert prompt.startswith("Base system prompt.")
    assert "Tool instructions:" in prompt
    assert "load_run_context" in prompt
    assert "persist_brief_draft" in prompt


def test_tool_registry_discovers_exported_decorated_tools() -> None:
    registry = build_tool_registry()

    for name in (
        "normalize_input",
        "assess_employer_readiness",
        "record_answer",
        "end_conversation",
    ):
        entry = registry.get(name)
        assert entry.name == name
        assert isinstance(entry.category, ToolCategory)


def test_tool_registry_terminal_flag_defaults_to_false() -> None:
    registry = build_tool_registry()

    assert registry.get("record_answer").is_terminal is False
    assert registry.get("normalize_input").is_terminal is False


def test_tool_registry_duplicate_names_fail_clearly() -> None:
    registry = build_tool_registry()
    entry = registry.get("normalize_input")

    with pytest.raises(ValueError, match="Duplicate tool registry entry"):
        ToolRegistry([entry, replace(entry)])


def test_tool_registry_scopes_to_selected_tool_names() -> None:
    registry = build_tool_registry().scoped(["record_answer"])

    assert registry.get("record_answer").name == "record_answer"
    with pytest.raises(KeyError, match="Unknown tool"):
        registry.get("normalize_input")


def test_provider_model_config_is_parsed_correctly() -> None:
    config = AgentWorkflowConfig.model_validate(
        {
            "role": "extractor",
            "provider": "anthropic",
            "model": "claude-3-5-haiku-latest",
            "system_prompt": "prompt",
            "temperature": 0.2,
            "max_tokens": 800,
            "timeout": 12,
            "tools": [],
            "can_handoff_to": [],
        }
    )
    settings = create_model_settings(config)

    assert config.provider == WorkflowProvider.ANTHROPIC
    assert config.model == "claude-3-5-haiku-latest"
    assert settings is not None
    assert settings["anthropic_cache_instructions"] is True
    assert settings["anthropic_cache_tool_definitions"] is True
    assert settings["anthropic_cache_messages"] is True
    assert settings["temperature"] == 0.2
    assert settings["max_tokens"] == 800
    assert settings["timeout"] == 12
    assert required_api_key_env_var(config.provider) == "ANTHROPIC_API_KEY"


def test_openai_model_settings_use_generic_provider_settings() -> None:
    settings = create_provider_model_settings(
        provider=WorkflowProvider.OPENAI,
        timeout=30,
        temperature=0.1,
        max_tokens=1200,
    )

    assert settings == {
        "temperature": 0.1,
        "max_tokens": 1200,
        "timeout": 30,
    }


def test_post_processor_config_loads_correctly() -> None:
    catalog = PostProcessorCatalog.model_validate(
        {
            "post_processors": [
                {
                    "key": "audit-tool-usage-and-handoffs",
                    "type": "audit_tool_usage_and_handoffs",
                    "description": "audit",
                    "provider": "anthropic",
                    "model": "claude-3-5-haiku-latest",
                    "system_prompt": "prompt",
                    "prompt_template": "template",
                }
            ]
        }
    )

    assert catalog.post_processors[0].type.value == "audit_tool_usage_and_handoffs"


def test_run_event_persistence_round_trip(db_session) -> None:
    run = create_run(db_session, RunCreateRequest(title="Workflow run"))
    event = record_run_event(
        db_session,
        run,
        RunEventPayload(
            event_type=RunEventType.TOOL_CALLED,
            agent_role="extractor",
            tool_name="load_run_context",
            tool_arguments={"stage": "extract"},
            tool_result={"loaded": True},
            message="Loaded normalized run context.",
        ),
    )
    stored = db_session.get(type(event), event.id)
    assert stored is not None

    serialized = serialize_run_event(event)
    assert serialized.tool_name == "load_run_context"
    assert serialized.tool_arguments == {"stage": "extract"}
    assert serialized.tool_result == {"loaded": True}


def test_runtime_tools_execute_through_registry() -> None:
    registry = build_tool_registry()

    normalized = registry.execute(
        "normalize_input", TextToolInput(text="  Need legal\n\nDecision approved  ")
    )
    sections = registry.execute(
        "split_into_sections", SectionsInput(text=normalized.text)
    )

    assert normalized.model_dump()["line_count"] == 2
    assert len(sections.model_dump()["sections"]) == 2


def test_workflow_execution_completes_and_persists_audit(db_session, tmp_path) -> None:
    settings = build_settings(tmp_path)
    registry = load_workflow_registry(settings)
    run = create_run(
        db_session,
        RunCreateRequest(
            title="Runtime run",
            input_text="Need legal summary\nDecision approved\nBudget risk is real",
        ),
    )

    executed = asyncio.run(execute_run_workflow(db_session, run, registry, settings))

    assert executed.status == "completed"
    assert executed.output_brief_serialized is not None
    assert executed.post_processor_results_serialized is not None
    events = db_session.query(Run).filter(Run.id == executed.id).one()
    assert events.follow_up_count == 0


def test_configured_parallel_extraction_events_are_persisted(
    db_session, tmp_path
) -> None:
    settings = build_settings(tmp_path)
    registry = load_workflow_registry(settings)
    run = create_run(
        db_session,
        RunCreateRequest(
            title="Parallel run", input_text="Need owner\nDecision approved"
        ),
    )

    asyncio.run(execute_run_workflow(db_session, run, registry, settings))

    event_rows = db_session.execute(
        text(
            "select tool_name, tool_result_json from run_events where run_id = :run_id"
        ),
        {"run_id": run.id},
    ).all()
    parallel_results = [
        row
        for row in event_rows
        if row.tool_name
        in {"extract_claims", "extract_decisions", "extract_action_items"}
        and row.tool_result_json
        and "parallel_group" in row.tool_result_json
    ]
    assert len(parallel_results) == 3


def test_invalid_handoff_fails_run_clearly(db_session, tmp_path) -> None:
    settings = build_settings(tmp_path)
    registry = load_workflow_registry(settings)
    workflow = registry.get_workflow("messy-notes-v1")
    workflow.agents["extractor"].config.can_handoff_to.clear()
    run = create_run(
        db_session,
        RunCreateRequest(title="Bad handoff", input_text="Need legal summary"),
    )

    with pytest.raises(WorkflowExecutionError, match="cannot hand off"):
        asyncio.run(execute_run_workflow(db_session, run, registry, settings))

    db_session.refresh(run)
    assert run.status == "failed"
    assert (
        db_session.query(RunEvent)
        .filter(RunEvent.run_id == run.id, RunEvent.event_type == "run_failed")
        .one()
        .message
    )


def test_startup_load_path_behaves_correctly(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    registry = load_workflow_registry(settings)

    assert (
        registry.get_workflow(settings.default_workflow_key).config.key
        == "messy-notes-v1"
    )
