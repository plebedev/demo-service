"""Tests for protected demo run endpoints."""

from __future__ import annotations

import asyncio

import pytest

from app.core.config import get_settings
from app.db.models import Run, RunEvent
from app.services.workflow_executor import WorkflowExecutionError, execute_run_workflow


def create_code(client, code: str) -> None:
    """Insert an invitation code through the admin API for test setup."""
    response = client.post(
        "/api/internal/admin/invitations",
        headers={"X-Admin-Secret": "test-admin-secret"},
        json={"code": code},
    )
    assert response.status_code == 201


def access_headers(client, code: str) -> dict[str, str]:
    """Redeem a code and return bearer auth headers."""
    create_code(client, code)
    redeem = client.post("/api/access/redeem", json={"code": code})
    assert redeem.status_code == 200
    token = redeem.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def build_extractable_pdf_bytes(text: str) -> bytes:
    """Create a minimal text-based PDF without pulling in extra tooling."""
    escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    content = f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET".encode("utf-8")
    objects = [
        b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj",
        b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj",
        b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >> endobj",
        b"4 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj",
        (
            b"5 0 obj << /Length "
            + str(len(content)).encode("ascii")
            + b" >> stream\n"
            + content
            + b"\nendstream endobj"
        ),
    ]

    output = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for obj in objects:
        offsets.append(len(output))
        output.extend(obj)
        output.extend(b"\n")

    xref_offset = len(output)
    output.extend(f"xref\n0 {len(offsets)}\n".encode("ascii"))
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))

    output.extend(
        (
            f"trailer << /Size {len(offsets)} /Root 1 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode("ascii")
    )
    return bytes(output)


def test_run_endpoints_require_access_token(client) -> None:
    response = client.get("/api/runs")
    assert response.status_code == 401
    assert response.json()["detail"] == "Access token required."


def test_create_and_get_run(client, db_session) -> None:
    headers = access_headers(client, "runs-create")

    created = client.post(
        "/api/runs",
        headers=headers,
        json={"title": "Ops intake", "input_text": "line one\nline two"},
    )
    assert created.status_code == 201
    payload = created.json()
    assert payload["status"] == "draft"
    assert payload["workflow_key"] == "messy-notes-v1"
    assert payload["title"] == "Ops intake"
    assert payload["input_text"] == "line one\nline two"
    assert payload["submitted_at"] is None
    assert payload["normalized_input_text"] is None

    stored = db_session.get(Run, payload["id"])
    assert stored is not None
    assert stored.status == "draft"

    fetched = client.get(f"/api/runs/{payload['id']}", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json()["id"] == payload["id"]


def test_list_runs_is_newest_first(client) -> None:
    headers = access_headers(client, "runs-list")

    first = client.post("/api/runs", headers=headers, json={"title": "First"})
    second = client.post("/api/runs", headers=headers, json={"title": "Second"})
    assert first.status_code == 201
    assert second.status_code == 201

    listing = client.get("/api/runs", headers=headers)
    assert listing.status_code == 200
    payload = listing.json()
    assert [run["title"] for run in payload["runs"]] == ["Second", "First"]


def test_update_run_draft(client, db_session) -> None:
    headers = access_headers(client, "runs-update")

    created = client.post("/api/runs", headers=headers, json={"title": "Raw title"})
    run_id = created.json()["id"]

    updated = client.put(
        f"/api/runs/{run_id}",
        headers=headers,
        json={
            "title": "Customer renewal brief",
            "input_text": "Budget pressure\nNeed Oracle-safe rollout",
            "input_metadata_json": {
                "source_kind": "pasted_text",
                "accepted_file_count": 0,
                "rejected_file_count": 0,
                "warning_count": 0,
            },
        },
    )
    assert updated.status_code == 200
    payload = updated.json()
    assert payload["status"] == "draft"
    assert payload["title"] == "Customer renewal brief"
    assert payload["input_metadata_json"]["source_kind"] == "pasted_text"

    stored = db_session.get(Run, run_id)
    assert stored is not None
    assert stored.input_text == "Budget pressure\nNeed Oracle-safe rollout"
    assert stored.input_metadata_serialized is not None
    assert stored.input_metadata_serialized.startswith('{"source_kind":"pasted_text"')


def test_submit_run_executes_workflow_to_completion(client, db_session) -> None:
    headers = access_headers(client, "runs-submit")

    created = client.post(
        "/api/runs",
        headers=headers,
        json={"title": "Needs submit", "input_text": "messy notes"},
    )
    run_id = created.json()["id"]

    submitted = client.post(
        f"/api/runs/{run_id}/submit",
        headers=headers,
        json={
            "title": "Submitted brief request",
            "input_text": "messy notes\nfollow-up capped",
            "input_metadata_json": {
                "source_kind": "pasted_text",
                "accepted_file_count": 0,
                "rejected_file_count": 0,
                "warning_count": 0,
            },
        },
    )
    assert submitted.status_code == 200
    payload = submitted.json()
    assert payload["status"] == "completed"
    assert payload["submitted_at"] is not None
    assert payload["completed_at"] is not None
    assert payload["output_brief_json"]["title"] == "Submitted brief request"
    assert (
        payload["post_processor_results_json"]["audit-tool-usage-and-handoffs"][
            "overall_assessment"
        ]
        == "ok"
    )

    stored = db_session.get(Run, run_id)
    assert stored is not None
    assert stored.status == "completed"
    assert stored.submitted_at is not None
    assert stored.input_metadata_serialized is not None
    assert stored.output_brief_serialized is not None

    events = (
        db_session.query(RunEvent)
        .filter(RunEvent.run_id == run_id)
        .order_by(RunEvent.id.asc())
        .all()
    )
    event_types = [event.event_type for event in events]
    assert "run_execution_started" in event_types
    assert "agent_started" in event_types
    assert "tool_called" in event_types
    assert "handoff_occurred" in event_types
    assert "run_completed" in event_types
    assert "post_processor_completed" in event_types

    conflict = client.post(
        f"/api/runs/{run_id}/submit",
        headers=headers,
        json={},
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"] == "Only draft or failed runs can be submitted."


def test_submit_without_payload_preserves_saved_draft_fields(
    client, db_session
) -> None:
    headers = access_headers(client, "runs-submit-preserve")

    created = client.post("/api/runs", headers=headers, json={"title": "Draft"})
    run_id = created.json()["id"]

    ingested = client.post(
        f"/api/runs/{run_id}/ingest",
        headers=headers,
        data={
            "title": "Saved title",
            "input_text": "Saved notes",
        },
        files=[
            (
                "files",
                ("notes.txt", b"Budget pressure\nKeep scope narrow", "text/plain"),
            )
        ],
    )
    assert ingested.status_code == 200

    submitted = client.post(
        f"/api/runs/{run_id}/submit",
        headers=headers,
    )
    assert submitted.status_code == 200
    payload = submitted.json()
    assert payload["status"] == "completed"
    assert payload["title"] == "Saved title"
    assert payload["input_text"] == "Saved notes"
    assert payload["uploaded_files_json"][0]["file_name"] == "notes.txt"
    assert payload["ingestion_summary_json"]["counts"]["accepted_files"] == 1

    stored = db_session.get(Run, run_id)
    assert stored is not None
    assert stored.title == "Saved title"
    assert stored.input_text == "Saved notes"
    assert stored.uploaded_files_serialized is not None


def test_run_events_endpoint_requires_access_and_returns_events(client) -> None:
    headers = access_headers(client, "runs-events")
    created = client.post(
        "/api/runs",
        headers=headers,
        json={"title": "Events", "input_text": "Need legal follow up"},
    )
    run_id = created.json()["id"]
    submitted = client.post(f"/api/runs/{run_id}/submit", headers=headers)
    assert submitted.status_code == 200

    unauthenticated = client.get(f"/api/runs/{run_id}/events")
    assert unauthenticated.status_code == 401

    response = client.get(f"/api/runs/{run_id}/events", headers=headers)
    assert response.status_code == 200
    payload = response.json()
    assert payload[0]["event_type"] == "run_execution_started"
    assert any(event["event_type"] == "post_processor_completed" for event in payload)

    summary = client.get(f"/api/runs/{run_id}/summary", headers=headers)
    assert summary.status_code == 200
    summary_payload = summary.json()
    assert summary_payload["status"] == "completed"
    assert "extract_action_items" in " ".join(summary_payload["tool_usage_summary"])
    assert "orchestrator to extractor" in summary_payload["handoff_summary"]
    assert summary_payload["audit_summary"] == (
        "Tool use and handoffs stayed inside the configured workflow."
    )


def test_failed_run_records_user_and_internal_failure_messages(
    client, db_session
) -> None:
    headers = access_headers(client, "runs-failure")
    created = client.post(
        "/api/runs",
        headers=headers,
        json={"title": "Bad workflow", "input_text": "notes"},
    )
    run_id = created.json()["id"]
    run = db_session.get(Run, run_id)
    assert run is not None
    run.workflow_key = "unknown-workflow"
    db_session.add(run)
    db_session.commit()
    db_session.refresh(run)

    with pytest.raises(WorkflowExecutionError):
        asyncio.run(
            execute_run_workflow(
                db_session,
                run,
                client.app.state.workflow_registry,
                get_settings(),
            )
        )

    db_session.refresh(run)
    assert run.status == "failed"
    assert run.failure_message == "The run failed during bounded workflow execution."
    assert "unknown-workflow" in (run.failure_internal_reason or "")

    summary = client.get(f"/api/runs/{run_id}/summary", headers=headers)
    assert summary.status_code == 200
    assert summary.json()["failure_message"] == (
        "The run failed during bounded workflow execution."
    )


def test_ingest_pasted_text(client, db_session) -> None:
    headers = access_headers(client, "runs-ingest-pasted")
    created = client.post("/api/runs", headers=headers, json={"title": "Draft"})
    run_id = created.json()["id"]

    response = client.post(
        f"/api/runs/{run_id}/ingest",
        headers=headers,
        data={"title": "Draft title", "input_text": "  Line one\nLine two  "},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["title"] == "Draft title"
    assert payload["input_text"] == "Line one\nLine two"
    assert payload["normalized_input_text"].startswith("Pasted notes:\nLine one")
    assert payload["input_metadata_json"]["source_kind"] == "pasted_text"
    assert payload["ingestion_summary_json"]["counts"]["accepted_pasted_text"] == 1

    stored = db_session.get(Run, run_id)
    assert stored is not None
    assert stored.normalized_input_text is not None
    assert stored.input_metadata_serialized is not None
    assert stored.uploaded_files_serialized == "[]"
    assert stored.ingestion_summary_serialized is not None


def test_ingest_plain_text_file(client) -> None:
    headers = access_headers(client, "runs-ingest-text-file")
    created = client.post("/api/runs", headers=headers, json={})
    run_id = created.json()["id"]

    response = client.post(
        f"/api/runs/{run_id}/ingest",
        headers=headers,
        data={"input_text": "Opening context"},
        files=[
            (
                "files",
                ("notes.txt", b"Budget pressure\nKeep scope narrow", "text/plain"),
            )
        ],
    )

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["uploaded_files_json"]) == 1
    assert payload["uploaded_files_json"][0]["file_name"] == "notes.txt"
    assert payload["uploaded_files_json"][0]["extracted_text"] == (
        "Budget pressure\nKeep scope narrow"
    )


def test_ingest_extractable_pdf(client) -> None:
    headers = access_headers(client, "runs-ingest-pdf")
    created = client.post("/api/runs", headers=headers, json={})
    run_id = created.json()["id"]

    response = client.post(
        f"/api/runs/{run_id}/ingest",
        headers=headers,
        files=[
            (
                "files",
                (
                    "notes.pdf",
                    build_extractable_pdf_bytes("Quarterly renewal call notes"),
                    "application/pdf",
                ),
            )
        ],
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["uploaded_files_json"][0]["file_name"] == "notes.pdf"
    assert (
        "Quarterly renewal call notes"
        in payload["uploaded_files_json"][0]["extracted_text"]
    )


def test_ingest_rejects_unsupported_file(client) -> None:
    headers = access_headers(client, "runs-ingest-unsupported")
    created = client.post("/api/runs", headers=headers, json={})
    run_id = created.json()["id"]

    response = client.post(
        f"/api/runs/{run_id}/ingest",
        headers=headers,
        files=[("files", ("photo.png", b"fake-image", "image/png"))],
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["uploaded_files_json"] == []
    rejected = payload["ingestion_summary_json"]["rejected_files"]
    assert rejected[0]["file_name"] == "photo.png"
    assert "Images are out for phase 1" in rejected[0]["reason"]


def test_ingest_rejects_oversized_file(client) -> None:
    headers = access_headers(client, "runs-ingest-big-file")
    created = client.post("/api/runs", headers=headers, json={})
    run_id = created.json()["id"]

    response = client.post(
        f"/api/runs/{run_id}/ingest",
        headers=headers,
        files=[
            (
                "files",
                ("big.txt", b"x" * (5_242_880 + 1), "text/plain"),
            )
        ],
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ingestion_summary_json"]["counts"]["rejected_files"] == 1
    assert (
        "size limit" in payload["ingestion_summary_json"]["rejected_files"][0]["reason"]
    )


def test_ingest_enforces_max_files(client) -> None:
    headers = access_headers(client, "runs-ingest-max-files")
    created = client.post("/api/runs", headers=headers, json={})
    run_id = created.json()["id"]

    response = client.post(
        f"/api/runs/{run_id}/ingest",
        headers=headers,
        files=[
            ("files", ("one.txt", b"one", "text/plain")),
            ("files", ("two.txt", b"two", "text/plain")),
            ("files", ("three.txt", b"three", "text/plain")),
            ("files", ("four.txt", b"four", "text/plain")),
        ],
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ingestion_summary_json"]["counts"]["accepted_files"] == 3
    assert payload["ingestion_summary_json"]["counts"]["rejected_files"] == 1
    assert payload["ingestion_summary_json"]["rejected_files"][0]["file_name"] == (
        "four.txt"
    )


def test_ingest_trims_to_workflow_limit(client) -> None:
    headers = access_headers(client, "runs-ingest-trim")
    created = client.post("/api/runs", headers=headers, json={})
    run_id = created.json()["id"]

    response = client.post(
        f"/api/runs/{run_id}/ingest",
        headers=headers,
        data={"input_text": "A" * 410_000},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ingestion_summary_json"]["counts"]["trimmed_pasted_text"] == 1
    assert payload["ingestion_summary_json"]["warnings"]
    assert payload["ingestion_summary_json"]["workflow_text_bytes"] <= 400_000


def test_ingest_trims_file_text_deterministically(client) -> None:
    headers = access_headers(client, "runs-ingest-file-trim")
    created = client.post("/api/runs", headers=headers, json={})
    run_id = created.json()["id"]

    response = client.post(
        f"/api/runs/{run_id}/ingest",
        headers=headers,
        files=[("files", ("long.txt", b"a" * 260_000, "text/plain"))],
    )

    assert response.status_code == 200
    payload = response.json()
    accepted_file = payload["uploaded_files_json"][0]
    assert accepted_file["trimmed"] is True
    assert accepted_file["extracted_text_bytes"] == 250_000
    assert any(
        "first extractable slice" in warning
        for warning in payload["ingestion_summary_json"]["warnings"]
    )


def test_ingest_endpoint_requires_access_token(client) -> None:
    seeded_headers = access_headers(client, "runs-ingest-auth")
    created = client.post("/api/runs", headers=seeded_headers, json={})
    run_id = created.json()["id"]

    response = client.post(
        f"/api/runs/{run_id}/ingest",
        data={"input_text": "secret-ish notes"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Access token required."


def test_sample_chaos_loading_works(client, db_session) -> None:
    headers = access_headers(client, "runs-samples")
    created = client.post("/api/runs", headers=headers, json={})
    run_id = created.json()["id"]

    catalog = client.get("/api/runs/samples", headers=headers)
    assert catalog.status_code == 200
    samples = catalog.json()["samples"]
    assert len(samples) >= 4

    loaded = client.post(
        f"/api/runs/{run_id}/sample",
        headers=headers,
        json={"sample_key": samples[0]["key"]},
    )
    assert loaded.status_code == 200
    payload = loaded.json()
    assert payload["title"] == samples[0]["title"]
    assert samples[0]["notes"][0] in payload["input_text"]
    assert payload["input_metadata_json"]["source_kind"].startswith("sample:")

    stored = db_session.get(Run, run_id)
    assert stored is not None
    assert stored.normalized_input_text is not None


def test_follow_up_allowed_exactly_once_and_persists(client, db_session) -> None:
    headers = access_headers(client, "runs-follow-up-once")
    created = client.post(
        "/api/runs",
        headers=headers,
        json={"title": "Follow-up brief", "input_text": "Decision approved"},
    )
    run_id = created.json()["id"]
    submitted = client.post(f"/api/runs/{run_id}/submit", headers=headers)
    assert submitted.status_code == 200

    follow_up = client.post(
        f"/api/runs/{run_id}/follow-up",
        headers=headers,
        json={"question": "Summarize only decisions from the brief?"},
    )
    assert follow_up.status_code == 200
    payload = follow_up.json()
    assert payload["follow_up_count"] == 1
    assert payload["follow_up_response_json"]["category"] == "decisions"

    second = client.post(
        f"/api/runs/{run_id}/follow-up",
        headers=headers,
        json={"question": "Clarify a contradiction?"},
    )
    assert second.status_code == 409

    stored = db_session.get(Run, run_id)
    assert stored is not None
    assert stored.follow_up_count == 1
    assert stored.follow_up_response_serialized is not None


def test_unrelated_follow_up_is_rejected(client) -> None:
    headers = access_headers(client, "runs-follow-up-unrelated")
    created = client.post(
        "/api/runs",
        headers=headers,
        json={"title": "Follow-up brief", "input_text": "Decision approved"},
    )
    run_id = created.json()["id"]
    assert client.post(f"/api/runs/{run_id}/submit", headers=headers).status_code == 200

    response = client.post(
        f"/api/runs/{run_id}/follow-up",
        headers=headers,
        json={"question": "Write me a recipe for lunch?"},
    )
    assert response.status_code == 400
    assert "Follow-up must stay about this brief" in response.json()["detail"]


def test_notification_preference_capture_validates_us_phone(client, db_session) -> None:
    headers = access_headers(client, "runs-notify")
    created = client.post("/api/runs", headers=headers, json={})
    run_id = created.json()["id"]

    invalid = client.post(
        f"/api/runs/{run_id}/notification-preference",
        headers=headers,
        json={"wants_sms": True, "phone_number": "12345"},
    )
    assert invalid.status_code == 422

    valid = client.post(
        f"/api/runs/{run_id}/notification-preference",
        headers=headers,
        json={"wants_sms": True, "phone_number": "(415) 555-0134"},
    )
    assert valid.status_code == 200
    payload = valid.json()
    assert payload["notification_preference_json"] == {
        "wants_sms": True,
        "phone_number": "+14155550134",
    }

    stored = db_session.get(Run, run_id)
    assert stored is not None
    assert stored.notification_preference_serialized is not None
