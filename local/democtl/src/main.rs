mod cli;
mod commands;
mod config;
mod http;
mod models;

use anyhow::Result;
use clap::Parser;
use cli::{Cli, Command};
use config::Config;
use http::DemoClient;

#[tokio::main]
async fn main() -> Result<()> {
    let cli = Cli::parse();
    let config = Config::from_cli(&cli)?;
    let client = DemoClient::new(config)?;

    match cli.command {
        Command::Admin(command) => commands::admin::run(&client, command).await,
        Command::Access(command) => commands::access::run(&client, command).await,
        Command::Runs(command) => commands::runs::run(&client, command).await,
        Command::Guardrails(command) => commands::guardrails::run(&client, command).await,
    }
}
