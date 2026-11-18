"""Standalone worker that executes one run in a separate OS process.

Used by the run-execution recovery tests to prove that leases, conflicts, and
recovery work across application processes rather than only across threads.
The worker reads database settings from the environment prepared by the test
fixtures and never contacts model or notification providers.

Exit codes: 0 when the run completed, 3 when execution returned HTTP 409.
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
import sys
import time

from fastapi import HTTPException
from pydantic import BaseModel

from app.core.config import get_settings
from app.db.models import Run
from app.db.session import get_session_factory
from app.services.workflow_executor import execute_run_workflow
from app.workflows.loader import load_workflow_registry

CONFLICT_EXIT_CODE = 3


def main() -> int:
    """Execute the requested run, optionally blocking inside one tool."""
    parser = argparse.ArgumentParser()
    parser.add_argument("run_id", type=int)
    parser.add_argument("--block-tool")
    parser.add_argument("--block-seconds", type=float, default=0.0)
    parser.add_argument("--marker")
    args = parser.parse_args()

    settings = get_settings()
    registry = load_workflow_registry(settings)
    original_execute = registry.tool_registry.execute

    def execute(name: str, payload: BaseModel) -> BaseModel:
        if name == args.block_tool:
            if args.marker:
                Path(args.marker).write_text(name, encoding="utf-8")
            time.sleep(args.block_seconds)
        return original_execute(name, payload)

    registry.tool_registry.execute = execute  # type: ignore[method-assign]

    session = get_session_factory()()
    try:
        run = session.get(Run, args.run_id)
        if run is None:
            print("run not found", flush=True)
            return 1
        try:
            executed = asyncio.run(
                execute_run_workflow(session, run, registry, settings)
            )
        except HTTPException as exc:
            print(f"conflict:{exc.status_code}:{exc.detail}", flush=True)
            return CONFLICT_EXIT_CODE if exc.status_code == 409 else 1
        print(f"status:{executed.status}", flush=True)
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    sys.exit(main())
