use std::fs;

use anyhow::{Context, Result};

use crate::cli::{AccessCommand, AccessSubcommand};
use crate::commands::print_json;
use crate::http::DemoClient;
use crate::models::{
    AccessTokenResponse, AccessTokenVerificationResponse, RedeemInvitationRequest,
};

pub async fn run(client: &DemoClient, command: AccessCommand) -> Result<()> {
    match command.command {
        AccessSubcommand::Redeem(args) => {
            let response: AccessTokenResponse = client
                .public_post_json(
                    "/api/access/redeem",
                    &RedeemInvitationRequest { code: args.code },
                )
                .await?;

            if let Some(path) = args.save_token {
                fs::write(&path, &response.access_token)
                    .with_context(|| format!("failed to write token to {}", path.display()))?;
            }

            if client.json_output() {
                return print_json(&response);
            }
            println!(
                "redeemed {} token for {} (expires {})",
                response.token_type, response.experience_id, response.expires_at
            );
            println!("redirect path: {}", response.redirect_path);
            Ok(())
        }
        AccessSubcommand::Verify(_) => {
            let response: AccessTokenVerificationResponse =
                client.authed_get("/api/access/verify").await?;
            if client.json_output() {
                return print_json(&response);
            }
            println!(
                "token {} for {} is {} until {}",
                response.token_id, response.experience_id, response.status, response.expires_at
            );
            println!("redirect path: {}", response.redirect_path);
            Ok(())
        }
    }
}
