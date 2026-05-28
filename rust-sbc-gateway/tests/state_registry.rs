use rust_sbc_gateway::state::{CallSession, CallState, SessionRegistry};

#[tokio::test]
async fn registry_updates_call_state() {
    let registry = SessionRegistry::new();
    registry.upsert(CallSession::new("session-a")).await;

    let updated = registry
        .update_state("session-a", CallState::WarmTransferActive)
        .await
        .expect("session should exist");
    assert_eq!(updated.current_state, CallState::WarmTransferActive);

    let fetched = registry
        .get("session-a")
        .await
        .expect("session should still exist");
    assert_eq!(fetched.current_state, CallState::WarmTransferActive);
}
