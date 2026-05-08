use std::path::PathBuf;

use clap::{Args, Parser, Subcommand};

#[derive(Debug, Parser)]
#[command(name = "democtl")]
#[command(about = "Local operator CLI for the invite-only demo")]
#[command(version)]
pub struct Cli {
    #[arg(long, env = "DEMOCTL_BASE_URL", default_value = "http://127.0.0.1:8000", global = true)]
    pub base_url: String,

    #[arg(long, env = "DEMOCTL_ADMIN_SECRET", global = true)]
    pub admin_secret: Option<String>,

    #[arg(long, global = true)]
    pub token: Option<String>,

    #[arg(long, global = true)]
    pub token_file: Option<PathBuf>,

    #[arg(long, global = true)]
    pub json: bool,

    #[command(subcommand)]
    pub command: Command,
}

#[derive(Debug, Subcommand)]
pub enum Command {
    Admin(AdminCommand),
    Access(AccessCommand),
    Runs(RunsCommand),
    Guardrails(GuardrailsCommand),
}

#[derive(Debug, Args)]
pub struct AdminCommand {
    #[command(subcommand)]
    pub command: AdminSubcommand,
}

#[derive(Debug, Subcommand)]
pub enum AdminSubcommand {
    Invites(AdminInvitesCommand),
}

#[derive(Debug, Args)]
pub struct AdminInvitesCommand {
    #[command(subcommand)]
    pub command: AdminInvitesSubcommand,
}

#[derive(Debug, Subcommand)]
pub enum AdminInvitesSubcommand {
    List,
    Create(CreateInviteArgs),
    Deactivate(DeactivateInviteArgs),
    Stats,
}

#[derive(Debug, Args)]
pub struct CreateInviteArgs {
    #[arg(long)]
    pub code: Option<String>,

    #[arg(long, default_value = "messy-notes")]
    pub label: String,

    #[arg(long)]
    pub max_uses: Option<u32>,
}

#[derive(Debug, Args)]
pub struct DeactivateInviteArgs {
    #[arg(long)]
    pub id: u64,
}

#[derive(Debug, Args)]
pub struct AccessCommand {
    #[command(subcommand)]
    pub command: AccessSubcommand,
}

#[derive(Debug, Subcommand)]
pub enum AccessSubcommand {
    Redeem(RedeemArgs),
    Verify(VerifyArgs),
}

#[derive(Debug, Args)]
pub struct RedeemArgs {
    #[arg(long)]
    pub code: String,

    #[arg(long)]
    pub save_token: Option<PathBuf>,
}

#[derive(Debug, Args)]
pub struct VerifyArgs {}

#[derive(Debug, Args)]
pub struct RunsCommand {
    #[command(subcommand)]
    pub command: RunsSubcommand,
}

#[derive(Debug, Subcommand)]
pub enum RunsSubcommand {
    List,
    Create(CreateRunArgs),
    Ingest(IngestRunArgs),
    Submit(RunIdArgs),
    Summary(RunIdArgs),
    Events(RunIdArgs),
}

#[derive(Debug, Args)]
pub struct CreateRunArgs {
    #[arg(long)]
    pub title: Option<String>,
}

#[derive(Debug, Args)]
pub struct IngestRunArgs {
    #[arg(long)]
    pub run_id: u64,

    #[arg(long)]
    pub title: Option<String>,

    #[arg(long)]
    pub text: Option<String>,

    #[arg(long)]
    pub text_file: Option<PathBuf>,
}

#[derive(Debug, Args)]
pub struct RunIdArgs {
    #[arg(long)]
    pub run_id: u64,
}

#[derive(Debug, Args)]
pub struct GuardrailsCommand {
    #[command(subcommand)]
    pub command: GuardrailsSubcommand,
}

#[derive(Debug, Subcommand)]
pub enum GuardrailsSubcommand {
    Check(GuardrailsCheckArgs),
}

#[derive(Debug, Args)]
pub struct GuardrailsCheckArgs {
    #[arg(long, default_value = "samples/guardrails")]
    pub fixtures: PathBuf,
}

#[cfg(test)]
mod tests {
    use super::*;
    use clap::CommandFactory;

    #[test]
    fn command_tree_is_valid() {
        Cli::command().debug_assert();
    }

    #[test]
    fn parses_admin_invites_list() {
        let cli = Cli::parse_from(["democtl", "admin", "invites", "list"]);
        assert!(matches!(
            cli.command,
            Command::Admin(AdminCommand {
                command: AdminSubcommand::Invites(AdminInvitesCommand {
                    command: AdminInvitesSubcommand::List
                })
            })
        ));
    }

    #[test]
    fn parses_access_redeem() {
        let cli = Cli::parse_from(["democtl", "access", "redeem", "--code", "demo-abc"]);
        assert!(matches!(
            cli.command,
            Command::Access(AccessCommand {
                command: AccessSubcommand::Redeem(_)
            })
        ));
    }

    #[test]
    fn parses_runs_create() {
        let cli = Cli::parse_from(["democtl", "runs", "create", "--title", "Rust smoke"]);
        assert!(matches!(
            cli.command,
            Command::Runs(RunsCommand {
                command: RunsSubcommand::Create(_)
            })
        ));
    }

    #[test]
    fn parses_runs_list() {
        let cli = Cli::parse_from(["democtl", "runs", "list"]);
        assert!(matches!(
            cli.command,
            Command::Runs(RunsCommand {
                command: RunsSubcommand::List
            })
        ));
    }

    #[test]
    fn parses_guardrails_check() {
        let cli = Cli::parse_from(["democtl", "guardrails", "check"]);
        assert!(matches!(
            cli.command,
            Command::Guardrails(GuardrailsCommand {
                command: GuardrailsSubcommand::Check(_)
            })
        ));
    }
}
