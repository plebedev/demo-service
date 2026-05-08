use std::fs;

use anyhow::{Context, Result};
use comfy_table::{Cell, Table};
use reqwest::multipart::{Form, Part};

use crate::cli::{IngestRunArgs, RunsCommand, RunsSubcommand};
use crate::commands::print_json;
use crate::http::DemoClient;
use crate::models::{
    RunCreateRequest, RunEventResponse, RunExecutionSummary, RunListResponse, RunResponse,
};

pub async fn run(client: &DemoClient, command: RunsCommand) -> Result<()> {
    match command.command {
        RunsSubcommand::List => {
            let response: RunListResponse = client.authed_get("/api/runs").await?;
            if client.json_output() {
                return print_json(&response);
            }
            print_run_table(&response.runs);
            Ok(())
        }
        RunsSubcommand::Create(args) => {
            let response: RunResponse = client
                .authed_post_json(
                    "/api/runs",
                    &RunCreateRequest {
                        title: args.title,
                        input_text: None,
                    },
                )
                .await?;
            print_run_response(client, &response)
        }
        RunsSubcommand::Ingest(args) => {
            let response = ingest_run(client, args).await?;
            print_run_response(client, &response)
        }
        RunsSubcommand::Submit(args) => {
            let response: RunResponse = client
                .authed_post_empty(&format!("/api/runs/{}/submit", args.run_id))
                .await?;
            print_run_response(client, &response)
        }
        RunsSubcommand::Summary(args) => {
            let response: RunExecutionSummary = client
                .authed_get(&format!("/api/runs/{}/summary", args.run_id))
                .await?;
            print_summary(client, &response)
        }
        RunsSubcommand::Events(args) => {
            let response: Vec<RunEventResponse> = client
                .authed_get(&format!("/api/runs/{}/events", args.run_id))
                .await?;
            if client.json_output() {
                return print_json(&response);
            }
            println!("{} events", response.len());
            for event in response {
                println!("{}", serde_json::to_string_pretty(&event)?);
            }
            Ok(())
        }
    }
}

pub async fn create_run(client: &DemoClient, title: Option<String>) -> Result<RunResponse> {
    client
        .authed_post_json(
            "/api/runs",
            &RunCreateRequest {
                title,
                input_text: None,
            },
        )
        .await
}

pub async fn ingest_run(client: &DemoClient, args: IngestRunArgs) -> Result<RunResponse> {
    let mut form = Form::new();
    if let Some(title) = args.title {
        form = form.text("title", title);
    }

    match (args.text, args.text_file) {
        (Some(_), Some(_)) => anyhow::bail!("use either --text or --text-file, not both"),
        (Some(text), None) => {
            form = form.text("input_text", text);
        }
        (None, Some(path)) => {
            let bytes = fs::read(&path)
                .with_context(|| format!("failed to read text file {}", path.display()))?;
            let file_name = path
                .file_name()
                .and_then(|value| value.to_str())
                .unwrap_or("notes.txt")
                .to_owned();
            let part = Part::bytes(bytes)
                .file_name(file_name)
                .mime_str("text/plain")
                .context("failed to prepare text file upload")?;
            form = form.part("files", part);
        }
        (None, None) => anyhow::bail!("ingest requires --text or --text-file"),
    }

    client
        .authed_post_multipart(&format!("/api/runs/{}/ingest", args.run_id), form)
        .await
}

pub fn print_run_response(client: &DemoClient, run: &RunResponse) -> Result<()> {
    if client.json_output() {
        return print_json(run);
    }

    println!(
        "run {} | status: {} | workflow: {} | title: {}",
        run.id,
        run.status,
        run.workflow_key,
        run.title.as_deref().unwrap_or("-")
    );

    if let Some(summary) = &run.ingestion_summary_json {
        println!(
            "ingestion: {} accepted files, {} rejected files, {} pasted text, {} workflow bytes",
            summary.counts.accepted_files,
            summary.counts.rejected_files,
            summary.counts.accepted_pasted_text,
            summary.workflow_text_bytes
        );
        for warning in &summary.warnings {
            println!("warning: {warning}");
        }

        if !summary.accepted_files.is_empty() {
            let mut table = Table::new();
            table.set_header(vec!["accepted file", "type", "bytes", "trimmed"]);
            for file in &summary.accepted_files {
                table.add_row(vec![
                    Cell::new(&file.file_name),
                    Cell::new(&file.content_type),
                    Cell::new(file.extracted_text_bytes),
                    Cell::new(file.trimmed),
                ]);
            }
            println!("{table}");
        }

        if !summary.rejected_files.is_empty() {
            let mut table = Table::new();
            table.set_header(vec!["rejected file", "type", "reason"]);
            for file in &summary.rejected_files {
                table.add_row(vec![
                    Cell::new(&file.file_name),
                    Cell::new(&file.content_type),
                    Cell::new(&file.reason),
                ]);
            }
            println!("{table}");
        }
    }

    if run.output_brief_json.is_some() {
        println!("output brief: present");
    }
    Ok(())
}

fn print_summary(client: &DemoClient, summary: &RunExecutionSummary) -> Result<()> {
    if client.json_output() {
        return print_json(summary);
    }

    println!("run {} | status: {}", summary.run_id, summary.status);
    if let Some(message) = &summary.failure_message {
        println!("failure: {message}");
    }
    print_lines("phases", &summary.phase_summary);
    print_lines("tools", &summary.tool_usage_summary);
    print_lines("handoffs", &summary.handoff_summary);
    if let Some(audit) = &summary.audit_summary {
        println!("audit: {audit}");
    }
    print_lines("post processors", &summary.post_processor_summary);
    Ok(())
}

fn print_lines(label: &str, lines: &[String]) {
    if lines.is_empty() {
        return;
    }
    println!("{label}:");
    for line in lines {
        println!("  - {line}");
    }
}

fn print_run_table(runs: &[RunResponse]) {
    let mut table = Table::new();
    table.set_header(vec!["id", "status", "workflow", "title"]);
    for run in runs {
        table.add_row(vec![
            Cell::new(run.id),
            Cell::new(&run.status),
            Cell::new(&run.workflow_key),
            Cell::new(run.title.as_deref().unwrap_or("-")),
        ]);
    }
    println!("{table}");
}
