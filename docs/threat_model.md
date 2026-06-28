# STRIDE Threat Modeling: Ambient Expense Agent

This document performs a systematic threat modeling assessment of the **Ambient Expense Agent** architecture following the STRIDE framework.

---

## 📐 System Boundaries & Data Flow

Below is the layout of trust zones and data paths:

```text
[ UNTRUSTED ZONE ]                       [ TRUSTED GCP ZONE ]

  +------------------+         (OIDC)         +--------------------------+
  | External Client  | ------------======---> | Pub/Sub Topic            |
  | (Expense Claims) |                        | (expense-reports)        |
  +------------------+                        +--------------------------+
                                                           |
                                                           | (OIDC Push Sub)
                                                           v
                                              +--------------------------+
                                              | Vertex AI Agent Runtime  |
                                              | (Reasoning Engine)       |
                                              +--------------------------+
                                                /                      \
                                               /                        \
                                              v                          v
                                      +---------------+          +---------------+
                                      | Session DB    |          | GCS Buckets / |
                                      | (SQLite/Cloud)|          | BigQuery Logs |
                                      +---------------+          +---------------+
                                              ^
                                              | (Read/Write)
                                              |
                                      +--------------------------+
                                      | Cloud Run                |
                                      | (Manager Dashboard UI)   |
                                      +--------------------------+
                                              ^
                                              | (HTTPS Ingress)
                                      [ Human Manager ]
```

---

## 🔒 STRIDE Threat Assessment & Mitigations

### 1. Spoofing (Identity Theft)
*   **Threat**: An unauthorized external attacker publishes false expense records directly to the agent endpoint, bypassing the Pub/Sub queue, or calls the dashboard API pretending to be the manager.
*   **Mitigation**:
    *   **OIDC Auth**: The Vertex AI Reasoning Engine exposes REST endpoints protected by Google IAM. The Pub/Sub subscription `expense-reports-push` is configured with an **OIDC push-auth service account** (`pubsub-invoker@...`). It signs every push request with an OIDC bearer token, which GCP validates before triggering the agent.
    *   **Workload Identity Federation (WIF)**: GitHub Actions workflows use short-lived federated OIDC tokens to authenticate deployments instead of static, committed JSON credentials.

### 2. Tampering (Data Modification)
*   **Threat**: An attacker alters the SQLite database file (`shared_sessions.db`) or tampers with the database session state to force approval status.
*   **Mitigation**:
    *   **Ignored Local Storage**: `shared_sessions.db` is strictly gitignored and excluded from version control to prevent local testing leakage.
    *   **Cloud Isolation**: In staging/production environments, the session storage backend uses Vertex AI's managed session service (`agentengine://`), which is fully isolated inside the customer's Google tenant project and protected by IAM permissions.

### 3. Repudiation (Denial of Action)
*   **Threat**: An approving manager approves a fraudulent high-value transaction but claims the system approved it automatically or that they never triggered the approval.
*   **Mitigation**:
    *   **Deterministic Attribution**: In the session storage and event payload outputs, the field `decision_by` is deterministically populated:
        *   `system` (if under $100 auto-approved).
        *   `human` (if approved manually via the manager dashboard).
    *   **Audit Logging**: Every agent step, tool call, and resumption event automatically exports telemetry to **Cloud Trace**, **BigQuery**, and **Cloud Logging**, creating a non-repudiable audit trail.

### 4. Information Disclosure (Data Leak)
*   **Threat**: Sensitive Personal Identifiable Information (PII) like Social Security Numbers (SSN) or Credit Card numbers are submitted in expense descriptions and leaked into public logs.
*   **Mitigation**:
    *   **PII Scrubbing Node**: Before any data reaches the Vertex AI LLM model, the [security_checkpoint](file:///Volumes/Investor/Learning/Google%205-Day%20AI%20Agents%20Intensive%20Course/ambient-expense-agent/expense_agent/agent.py#L219) node runs a regex-based regex-scrubbing filter (`scrub_pii`) to replace SSNs and Credit Card numbers with `[REDACTED SSN]` and `[REDACTED CREDIT CARD]`.

### 5. Denial of Service (System Resource Exhaustion)
*   **Threat**: An attacker floods the Pub/Sub topic with malformed messages to crash the agent runtime or exhaust memory on the dashboard.
*   **Mitigation**:
    *   **Dead-Letter Queue (DLQ)**: The Pub/Sub push subscription routes failing payloads to a dedicated DLQ (`expense-reports-dead-letter`) after a maximum of **5 failed delivery attempts**, preventing queue poisoning and infinite retries.
    *   **Memory Allocations**: The Manager Dashboard Cloud Run container is provisioned with **`1Gi`** of RAM (`--memory=1Gi`) to guarantee stable container startups under heavy loading without triggering 503 out-of-memory errors.

### 6. Elevation of Privilege (Access Escalation)
*   **Threat A (Prompt Injection)**: An attacker submits a description instructing the LLM to ignore standard thresholds and auto-approve a high-value purchase.
    *   *Mitigation*: The threshold check is implemented in **deterministic python code** in the `parse_event` node, not evaluated by the LLM. Furthermore, the LLM agent (`review_risk`) has **no tools** bound to it (no shell, file, or API access), ensuring it operates in a sandbox without system execution capabilities.
*   **Threat B (Pipeline Hijack)**: A compromised GitHub Actions runner modifies IAM permissions on GCP.
    *   *Mitigation*: **Privilege Escalation Prevention**. The CI/CD service account does not hold owner or `roles/resourcemanager.projectIamAdmin` roles. High-privilege tasks (like WIF provisioning) are executed once locally by a human administrator; the runner is limited purely to operational deployment roles (`roles/run.admin`, `roles/aiplatform.user`).
