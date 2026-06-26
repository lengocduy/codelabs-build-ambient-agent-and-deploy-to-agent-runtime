# Troubleshooting Guide

This guide helps debug and resolve common runtime, connection, and database issues in the Ambient Expense Agent project.

---

## 🔌 1. Pub/Sub Message Delivery & Connection Issues

If you publish a test message (e.g., via `make pubsub-message-manual-approval`) and the agent does not appear to receive it, check the subscription configuration.

### Common Cause A: Missing OIDC authentication or payload wrapping on GCP
Running `gcloud pubsub subscriptions update` without the proper flags can wipe out push endpoint credentials and payload formatting options.

#### Verification
Describe your subscription and check the push configuration:
```bash
gcloud pubsub subscriptions describe expense-reports-push --project=<YOUR_PROJECT_ID>
```
Look for:
1. `oidcToken` (specifically `serviceAccountEmail` set to `pubsub-invoker@...`)
2. `wrapper` (it should have `noWrapper` enabled)

#### Resolution
Re-run the setup script or target:
```bash
make pubsub-setup \
  PROJECT_ID=<YOUR_PROJECT_ID> \
  REGION=us-east1 \
  PROJECT_NUMBER=<YOUR_PROJECT_NUMBER> \
  REASONING_ENGINE_ID=<YOUR_REASONING_ENGINE_ID>
```

### Common Cause B: Stale Reasoning Engine ID
If the reasoning engine was redeployed, the push subscription endpoint might be pointing to a deleted/expired engine ID.

#### Verification
Check if the endpoint URL in your subscription matches your active reasoning engine:
```bash
gcloud beta ai reasoning-engines list --project=<YOUR_PROJECT_ID> --region=us-east1
```

#### Resolution
Update the subscription with the new `REASONING_ENGINE_ID` using `make pubsub-setup` as shown above.

---

## 💾 2. Dashboard Session Sync & Approval State Issues

If you approve an expense on the Manager Dashboard but it does not resume the agent or update the state, check the session user identifier.

### Common Cause: `user_id` Mismatch in Local SQLite Offline Mode
The database expects a specific `user_id` when retrieving or resuming a session, but the dashboard might be executing or querying under a different user identifier.

* **Database/Agent expectation**: The incoming Pub/Sub message or local test runner might use `ambient_system` or `user` as the session owner.
* **Dashboard default**: The Manager Dashboard UI might run with a hardcoded `default-user` identity.

If they mismatch, the dashboard will not display the pending approvals or will fail to resume the correct session.

#### Verification
Check the sessions inside the local SQLite database to see what `user_id` is registered:
```bash
uv run python -c "
import sqlite3
conn = sqlite3.connect('shared_sessions.db')
cursor = conn.cursor()
cursor.execute('SELECT id, user_id, state FROM sessions')
for row in cursor.fetchall():
    print(f'Session ID: {row[0]} | User ID: {row[1]} | State: {row[2][:50]}...')
"
```

#### Resolution
Ensure the client/simulation payloads and the dashboard config align on the same `user_id` value. 
* To simulate local Pub/Sub events with the matching `user_id`, make sure the payload JSON contains:
  ```json
  {"input": {"message": "...", "user_id": "ambient_system"}}
  ```
* Ensure your `.env.local` or dashboard configuration resolves the correct user context.
