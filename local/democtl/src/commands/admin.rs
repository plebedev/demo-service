use anyhow::Result;
use comfy_table::{Cell, Table};

use crate::cli::{AdminCommand, AdminInvitesSubcommand, AdminSubcommand};
use crate::commands::print_json;
use crate::http::DemoClient;
use crate::models::{CreateInvitationCodeRequest, InvitationCode, InvitationStats};

pub async fn run(client: &DemoClient, command: AdminCommand) -> Result<()> {
    match command.command {
        AdminSubcommand::Invites(invites) => match invites.command {
            AdminInvitesSubcommand::List => list_invites(client).await,
            AdminInvitesSubcommand::Create(args) => {
                let payload = CreateInvitationCodeRequest {
                    code: args.code,
                    label: args.label,
                    max_uses: args.max_uses,
                };
                let invite: InvitationCode = client
                    .admin_post_json("/api/internal/admin/invitations", &payload)
                    .await?;
                print_invite_result(client, "Created invitation code", &invite)
            }
            AdminInvitesSubcommand::Deactivate(args) => {
                let invite: InvitationCode = client
                    .admin_post_empty(&format!(
                        "/api/internal/admin/invitations/{}/deactivate",
                        args.id
                    ))
                    .await?;
                print_invite_result(client, "Deactivated invitation code", &invite)
            }
            AdminInvitesSubcommand::Stats => stats(client).await,
        },
    }
}

async fn list_invites(client: &DemoClient) -> Result<()> {
    let invites: Vec<InvitationCode> = client.admin_get("/api/internal/admin/invitations").await?;
    if client.json_output() {
        return print_json(&invites);
    }
    print_invite_table(&invites);
    Ok(())
}

async fn stats(client: &DemoClient) -> Result<()> {
    let stats: InvitationStats = client
        .admin_get("/api/internal/admin/invitations/stats")
        .await?;
    if client.json_output() {
        return print_json(&stats);
    }

    println!(
        "total codes: {} | active codes: {} | total redemptions: {}",
        stats.total_codes, stats.active_codes, stats.total_redemptions
    );
    print_invite_table(&stats.codes);
    Ok(())
}

fn print_invite_result(client: &DemoClient, label: &str, invite: &InvitationCode) -> Result<()> {
    if client.json_output() {
        return print_json(invite);
    }
    println!("{label}: {} (id {})", invite.code, invite.id);
    print_invite_table(std::slice::from_ref(invite));
    Ok(())
}

fn print_invite_table(invites: &[InvitationCode]) {
    let mut table = Table::new();
    table.set_header(vec![
        "id",
        "code",
        "label",
        "active",
        "uses",
        "max uses",
        "created",
        "last used",
    ]);

    for invite in invites {
        table.add_row(vec![
            Cell::new(invite.id),
            Cell::new(&invite.code),
            Cell::new(invite.label.as_deref().unwrap_or("-")),
            Cell::new(invite.is_active),
            Cell::new(invite.use_count),
            Cell::new(
                invite
                    .max_uses
                    .map(|value| value.to_string())
                    .unwrap_or_else(|| "-".to_owned()),
            ),
            Cell::new(&invite.created_at),
            Cell::new(invite.last_used_at.as_deref().unwrap_or("-")),
        ]);
    }

    println!("{table}");
}
