use anyhow::{Context, Result};
use reqwest::header::{HeaderMap, HeaderValue, AUTHORIZATION};
use reqwest::{multipart, Response};
use serde::de::DeserializeOwned;
use serde::Serialize;
use serde_json::Value;
use url::Url;

use crate::config::Config;

#[derive(Clone)]
pub struct DemoClient {
    client: reqwest::Client,
    config: Config,
}

impl DemoClient {
    pub fn new(config: Config) -> Result<Self> {
        Ok(Self {
            client: reqwest::Client::builder().build()?,
            config,
        })
    }

    pub fn json_output(&self) -> bool {
        self.config.json
    }

    pub fn path_url(&self, path: &str) -> Result<Url> {
        path_url(&self.config.base_url, path)
    }

    pub async fn admin_get<T: DeserializeOwned>(&self, path: &str) -> Result<T> {
        let secret = self.config.require_admin_secret()?;
        let response = self
            .client
            .get(self.path_url(path)?)
            .header("X-Admin-Secret", secret)
            .send()
            .await?;
        parse_response(response).await
    }

    pub async fn admin_post_json<T: DeserializeOwned, B: Serialize>(
        &self,
        path: &str,
        body: &B,
    ) -> Result<T> {
        let secret = self.config.require_admin_secret()?;
        let response = self
            .client
            .post(self.path_url(path)?)
            .header("X-Admin-Secret", secret)
            .json(body)
            .send()
            .await?;
        parse_response(response).await
    }

    pub async fn admin_post_empty<T: DeserializeOwned>(&self, path: &str) -> Result<T> {
        let secret = self.config.require_admin_secret()?;
        let response = self
            .client
            .post(self.path_url(path)?)
            .header("X-Admin-Secret", secret)
            .send()
            .await?;
        parse_response(response).await
    }

    pub async fn public_post_json<T: DeserializeOwned, B: Serialize>(
        &self,
        path: &str,
        body: &B,
    ) -> Result<T> {
        let response = self.client.post(self.path_url(path)?).json(body).send().await?;
        parse_response(response).await
    }

    pub async fn authed_get<T: DeserializeOwned>(&self, path: &str) -> Result<T> {
        let response = self
            .client
            .get(self.path_url(path)?)
            .headers(self.auth_headers()?)
            .send()
            .await?;
        parse_response(response).await
    }

    pub async fn authed_post_json<T: DeserializeOwned, B: Serialize>(
        &self,
        path: &str,
        body: &B,
    ) -> Result<T> {
        let response = self
            .client
            .post(self.path_url(path)?)
            .headers(self.auth_headers()?)
            .json(body)
            .send()
            .await?;
        parse_response(response).await
    }

    pub async fn authed_post_empty<T: DeserializeOwned>(&self, path: &str) -> Result<T> {
        let response = self
            .client
            .post(self.path_url(path)?)
            .headers(self.auth_headers()?)
            .send()
            .await?;
        parse_response(response).await
    }

    pub async fn authed_post_multipart<T: DeserializeOwned>(
        &self,
        path: &str,
        form: multipart::Form,
    ) -> Result<T> {
        let response = self
            .client
            .post(self.path_url(path)?)
            .headers(self.auth_headers()?)
            .multipart(form)
            .send()
            .await?;
        parse_response(response).await
    }

    fn auth_headers(&self) -> Result<HeaderMap> {
        let token = self.config.require_token()?;
        let mut headers = HeaderMap::new();
        let value = HeaderValue::from_str(&format!("Bearer {token}"))
            .context("access token contained invalid header characters")?;
        headers.insert(AUTHORIZATION, value);
        Ok(headers)
    }
}

pub fn path_url(base_url: &Url, path: &str) -> Result<Url> {
    let normalized = path.trim_start_matches('/');
    base_url
        .join(normalized)
        .with_context(|| format!("failed to join URL path {path}"))
}

pub async fn parse_response<T: DeserializeOwned>(response: Response) -> Result<T> {
    let status = response.status();
    let text = response.text().await.unwrap_or_default();
    if !status.is_success() {
        anyhow::bail!("{}", format_backend_error(status.as_u16(), &text));
    }
    serde_json::from_str(&text).with_context(|| {
        format!(
            "backend returned status {status}, but the response did not match the expected schema"
        )
    })
}

pub fn format_backend_error(status: u16, body: &str) -> String {
    if let Ok(value) = serde_json::from_str::<Value>(body) {
        if let Some(detail) = value.get("detail") {
            if let Some(message) = detail.as_str() {
                return format!("backend error {status}: {message}");
            }
            return format!("backend error {status}: {detail}");
        }
        return format!("backend error {status}: {value}");
    }

    let trimmed = body.trim();
    if trimmed.is_empty() {
        format!("backend error {status}")
    } else {
        format!("backend error {status}: {trimmed}")
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn joins_api_paths() {
        let base = Url::parse("http://127.0.0.1:8000/").unwrap();
        assert_eq!(
            path_url(&base, "/api/runs").unwrap().as_str(),
            "http://127.0.0.1:8000/api/runs"
        );
    }

    #[test]
    fn formats_string_detail_error() {
        assert_eq!(
            format_backend_error(404, r#"{"detail":"Invitation code not found."}"#),
            "backend error 404: Invitation code not found."
        );
    }

    #[test]
    fn formats_structured_detail_error() {
        assert_eq!(
            format_backend_error(422, r#"{"detail":[{"msg":"bad"}]}"#),
            r#"backend error 422: [{"msg":"bad"}]"#
        );
    }
}
