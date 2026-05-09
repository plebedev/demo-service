use std::fs;
use std::path::{Path, PathBuf};

use anyhow::{Context, Result};
use comfy_table::{Cell, Table};
use reqwest::multipart::{Form, Part};

use crate::cli::{GuardrailsCommand, GuardrailsSubcommand};
use crate::commands::runs;
use crate::http::DemoClient;
use crate::models::RunResponse;

struct GuardrailCase {
    name: &'static str,
    path: PathBuf,
    file_name: &'static str,
    mime_type: &'static str,
    expect_rejection: bool,
}

struct GuardrailResult {
    name: &'static str,
    passed: bool,
    detail: String,
}

pub async fn run(client: &DemoClient, command: GuardrailsCommand) -> Result<()> {
    match command.command {
        GuardrailsSubcommand::Check(args) => check(client, &args.fixtures).await,
    }
}

async fn check(client: &DemoClient, fixtures: &Path) -> Result<()> {
    let accepted_path = fixtures.join("accepted.txt");
    let accepted_text = fs::read_to_string(&accepted_path)
        .with_context(|| format!("failed to read {}", accepted_path.display()))?;
    let run = runs::create_run(client, Some("Rust guardrail check".to_owned())).await?;

    let accepted_response: RunResponse = client
        .authed_post_multipart(
            &format!("/api/runs/{}/ingest", run.id),
            Form::new().text("input_text", accepted_text),
        )
        .await?;

    let mut results = Vec::new();
    let accepted_summary = accepted_response.ingestion_summary_json.as_ref();
    let accepted_count = accepted_summary
        .map(|summary| summary.counts.accepted_pasted_text + summary.counts.accepted_files)
        .unwrap_or(0);
    results.push(GuardrailResult {
        name: "accepted plain text",
        passed: accepted_count > 0,
        detail: format!("accepted input count: {accepted_count}"),
    });

    let cases = vec![
        GuardrailCase {
            name: "image upload rejected",
            path: fixtures.join("rejected-image-placeholder.png.txt"),
            file_name: "rejected-image-placeholder.png",
            mime_type: "image/png",
            expect_rejection: true,
        },
        GuardrailCase {
            name: "audio upload rejected",
            path: fixtures.join("rejected-audio-placeholder.mp3.txt"),
            file_name: "rejected-audio-placeholder.mp3",
            mime_type: "audio/mpeg",
            expect_rejection: true,
        },
        GuardrailCase {
            name: "json upload rejected",
            path: fixtures.join("unsupported.json"),
            file_name: "unsupported.json",
            mime_type: "application/json",
            expect_rejection: true,
        },
    ];

    for case in cases {
        results.push(run_case(client, run.id, case).await?);
    }

    if client.json_output() {
        let value = serde_json::json!({
            "run_id": run.id,
            "results": results.iter().map(|result| {
                serde_json::json!({
                    "name": result.name,
                    "passed": result.passed,
                    "detail": result.detail,
                })
            }).collect::<Vec<_>>()
        });
        println!("{}", serde_json::to_string_pretty(&value)?);
    } else {
        println!("guardrail check run: {}", run.id);
        let mut table = Table::new();
        table.set_header(vec!["case", "result", "detail"]);
        for result in &results {
            table.add_row(vec![
                Cell::new(result.name),
                Cell::new(if result.passed { "pass" } else { "fail" }),
                Cell::new(&result.detail),
            ]);
        }
        println!("{table}");
    }

    if results.iter().any(|result| !result.passed) {
        anyhow::bail!("one or more input guardrail checks failed");
    }
    Ok(())
}

async fn run_case(client: &DemoClient, run_id: u64, case: GuardrailCase) -> Result<GuardrailResult> {
    let bytes =
        fs::read(&case.path).with_context(|| format!("failed to read {}", case.path.display()))?;
    let part = Part::bytes(bytes)
        .file_name(case.file_name)   // Cow::Borrowed, no allocation
        .mime_str(case.mime_type)
        .with_context(|| format!("failed to prepare {}", case.file_name))?;
    let response: RunResponse = client
        .authed_post_multipart(
            &format!("/api/runs/{run_id}/ingest"),
            Form::new().part("files", part),
        )
        .await?;
    let rejected = response
        .ingestion_summary_json
        .as_ref()
        .map(|summary| summary.rejected_files.as_slice())
        .unwrap_or(&[]);
    let reason = rejected
        .iter()
        .find(|file| file.file_name == case.file_name)
        .map(|file| file.reason.clone());
    let passed = if case.expect_rejection {
        reason.is_some()
    } else {
        reason.is_none()
    };
    Ok(GuardrailResult {
        name: case.name,
        passed,
        detail: reason.unwrap_or_else(|| "no rejection reason recorded".to_owned()),
    })
}
