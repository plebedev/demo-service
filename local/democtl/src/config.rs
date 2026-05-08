use std::fs;
use std::path::PathBuf;

use anyhow::{Context, Result};
use url::Url;

use crate::cli::Cli;

#[derive(Debug, Clone)]
pub struct Config {
    pub base_url: Url,
    pub admin_secret: Option<String>,
    pub token: Option<String>,
    pub token_file: Option<PathBuf>,
    pub json: bool,
}

impl Config {
    pub fn from_cli(cli: &Cli) -> Result<Self> {
        let base_url = parse_base_url(&cli.base_url)?;
        Ok(Self {
            base_url,
            admin_secret: cli.admin_secret.clone(),
            token: cli.token.clone(),
            token_file: cli.token_file.clone(),
            json: cli.json,
        })
    }

    pub fn require_admin_secret(&self) -> Result<&str> {
        self.admin_secret
            .as_deref()
            .filter(|value| !value.trim().is_empty())
            .context("admin secret required; pass --admin-secret or set DEMOCTL_ADMIN_SECRET")
    }

    pub fn require_token(&self) -> Result<String> {
        if let Some(token) = self.token.as_deref().filter(|value| !value.trim().is_empty()) {
            return Ok(token.to_owned());
        }

        let token_file = self
            .token_file
            .as_ref()
            .context("access token required; pass --token or --token-file")?;
        let token = fs::read_to_string(token_file)
            .with_context(|| format!("failed to read token file {}", token_file.display()))?
            .trim()
            .to_owned();
        if token.is_empty() {
            anyhow::bail!("token file {} was empty", token_file.display());
        }
        Ok(token)
    }
}

pub fn parse_base_url(value: &str) -> Result<Url> {
    let mut url = Url::parse(value).with_context(|| format!("invalid base URL: {value}"))?;
    if url.cannot_be_a_base() {
        anyhow::bail!("base URL must be an HTTP(S) base URL");
    }
    if url.scheme() != "http" && url.scheme() != "https" {
        anyhow::bail!("base URL must use http or https");
    }
    url.set_query(None);
    url.set_fragment(None);
    Ok(url)
}

#[cfg(test)]
mod tests {
    use std::io::Write;

    use clap::Parser;
    use tempfile::NamedTempFile;

    use super::*;
    use crate::cli::Cli;

    #[test]
    fn parses_base_url() {
        let url = parse_base_url("http://127.0.0.1:8000").unwrap();
        assert_eq!(url.as_str(), "http://127.0.0.1:8000/");
    }

    #[test]
    fn rejects_non_http_base_url() {
        let err = parse_base_url("file:///tmp/demo").unwrap_err();
        assert!(err.to_string().contains("http or https"));
    }

    #[test]
    fn config_reads_cli_values() {
        let cli = Cli::parse_from([
            "democtl",
            "--base-url",
            "http://localhost:8000",
            "--admin-secret",
            "secret",
            "--json",
            "admin",
            "invites",
            "list",
        ]);
        let config = Config::from_cli(&cli).unwrap();
        assert_eq!(config.base_url.as_str(), "http://localhost:8000/");
        assert_eq!(config.require_admin_secret().unwrap(), "secret");
        assert!(config.json);
    }

    #[test]
    fn direct_token_beats_token_file() {
        let mut file = NamedTempFile::new().unwrap();
        writeln!(file, "file-token").unwrap();
        let cli = Cli::parse_from([
            "democtl",
            "--token",
            "direct-token",
            "--token-file",
            file.path().to_str().unwrap(),
            "access",
            "verify",
        ]);
        let config = Config::from_cli(&cli).unwrap();
        assert_eq!(config.require_token().unwrap(), "direct-token");
    }

    #[test]
    fn reads_token_file() {
        let mut file = NamedTempFile::new().unwrap();
        writeln!(file, "file-token").unwrap();
        let cli = Cli::parse_from([
            "democtl",
            "--token-file",
            file.path().to_str().unwrap(),
            "access",
            "verify",
        ]);
        let config = Config::from_cli(&cli).unwrap();
        assert_eq!(config.require_token().unwrap(), "file-token");
    }
}
