use std::collections::HashMap;
use std::sync::Arc;

use tokio::sync::{mpsc, Mutex};

#[derive(Debug, Clone, Copy, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
pub enum CallState {
    NormalCall,
    WarmTransferActive,
    TransferComplete,
}

#[derive(Debug, Clone)]
pub struct WebSocketFrame {
    pub bytes: Vec<u8>,
}

#[derive(Debug, Clone)]
pub struct CallSession {
    pub session_id: String,
    pub current_state: CallState,
    pub browser_ws_tx: Option<mpsc::Sender<WebSocketFrame>>,
    pub outbound_sip_rtp_tx: Option<mpsc::Sender<Vec<u8>>>,
    pub ai_engine_tx: Option<mpsc::Sender<Vec<u8>>>,
}

impl CallSession {
    pub fn new(session_id: impl Into<String>) -> Self {
        Self {
            session_id: session_id.into(),
            current_state: CallState::NormalCall,
            browser_ws_tx: None,
            outbound_sip_rtp_tx: None,
            ai_engine_tx: None,
        }
    }
}

#[derive(Debug, Clone)]
pub struct SessionRegistry {
    inner: Arc<Mutex<HashMap<String, CallSession>>>,
}

impl SessionRegistry {
    pub fn new() -> Self {
        Self {
            inner: Arc::new(Mutex::new(HashMap::new())),
        }
    }

    pub async fn upsert(&self, session: CallSession) {
        let mut guard = self.inner.lock().await;
        guard.insert(session.session_id.clone(), session);
    }

    pub async fn get(&self, session_id: &str) -> Option<CallSession> {
        let guard = self.inner.lock().await;
        guard.get(session_id).cloned()
    }

    pub async fn update_state(
        &self,
        session_id: &str,
        new_state: CallState,
    ) -> Option<CallSession> {
        let mut guard = self.inner.lock().await;
        let session = guard.get_mut(session_id)?;
        session.current_state = new_state;
        Some(session.clone())
    }

    pub async fn remove(&self, session_id: &str) {
        let mut guard = self.inner.lock().await;
        guard.remove(session_id);
    }

    pub async fn list(&self) -> Vec<CallSession> {
        let guard = self.inner.lock().await;
        guard.values().cloned().collect()
    }
}

impl Default for SessionRegistry {
    fn default() -> Self {
        Self::new()
    }
}
