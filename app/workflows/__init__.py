"""Workflow configuration and runtime scaffolding."""

from app.workflows.loader import WorkflowRegistry, load_workflow_registry

__all__ = ["WorkflowRegistry", "load_workflow_registry"]
