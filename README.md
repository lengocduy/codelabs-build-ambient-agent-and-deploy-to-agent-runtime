# Ambient Expense Agent

An event-driven ReAct agent built with the Google Agent Development Kit (ADK) that processes incoming expense claims, performs automated audits, and hooks up to a manager approval dashboard for human-in-the-loop decisions.

---

## 📐 Architecture Overview

This diagram represents the high-level event-driven topology of the system:

![Architecture Flow](/arts/architecture_1920.png)

1. **Event Ingestion**: Raw expense report JSON payloads are published to Google Cloud Pub/Sub, which triggers the deployed Vertex AI Reasoning Engine agent through an OIDC-authenticated Push Subscription.
2. **Auto-Approval**: The agent audits the expense claims. Low-value expenses (< $100) are processed and approved instantly without human intervention.
3. **Human-in-the-Loop Interrupt**: High-value expenses (>= $100) or those raising security concerns trigger a human intervention pause (`RequestInput` event named `human_approval`), saving state to the session service.
4. **Manager Resolution**: A standalone FastAPI Manager Dashboard polls the session storage (either local SQLite or Cloud Vertex AI session service), displaying pending approvals, and sending resumption signals back to the Agent Runtime to resume execution.

---

## 📂 Project Structure

```text
ambient-expense-agent/
├── .github/workflows/         # Automated GitHub Actions pipelines
│   ├── deploy-to-prod.yaml    # Production deployment and review gate
│   ├── pr_checks.yaml         # Pull request testing & validation
│   ├── staging.yaml           # Staging build & deployment
│   └── teardown.yaml          # Automated infrastructure teardown
├── expense_agent/             # Core ReAct agent code
│   ├── app_utils/             # App utilities (telemetry, typing)
│   ├── agent.py               # Main agent logic (audit logic & state machine)
│   ├── agent_runtime_app.py   # Entry point for Agent Runtime deployment
│   ├── config.py              # Central agent configuration
│   └── fast_api_app.py        # Local API wrapping the agent
├── submission_frontend/       # Manager Dashboard service (FastAPI app, see [submission_frontend/README.md](file:///Volumes/Investor/Learning/Google%205-Day%20AI%20Agents%20Intensive%20Course/ambient-expense-agent/submission_frontend/README.md))
├── tests/                     # Unit, integration, and load tests
├── Dockerfile                 # Root level Dockerfile for multi-service deployment
├── GEMINI.md                  # AI-assisted development guide
├── Makefile                   # Automation shortcuts for local testing and deployment
├── pyproject.toml             # Root project dependencies & configuration
├── uv.lock                    # Dependency lockfile
└── agents-cli-manifest.yaml   # Manifest for google-agents-cli
```

> 💡 **Tip:** Use [Gemini CLI](https://github.com/google-gemini/gemini-cli) for AI-assisted development - project context is pre-configured in `GEMINI.md`.

---

## 📋 Requirements

### 1. Local Development Environment
* **Python**: `3.11` (>=3.11, <3.14 recommended)
* **uv**: Astral's package installer (used for all dependency management) - [Install](https://docs.astral.sh/uv/getting-started/installation/)
* **agents-cli**: Google Agent Development Kit CLI. Install via:
  ```bash
  uv tool install google-agents-cli
  ```
* **Google Cloud SDK (`gcloud`)**: Required for deployment, Pub/Sub provisioning, and IAM setup - [Install](https://cloud.google.com/sdk/docs/install)

### 2. Google Cloud Setup & Enabled APIs
To run or deploy resources on Google Cloud, ensure billing is enabled and activate the required services:
```bash
gcloud services enable \
  aiplatform.googleapis.com \
  run.googleapis.com \
  pubsub.googleapis.com \
  cloudbuild.googleapis.com
```

### 3. IAM Roles & Service Accounts
* **Vertex AI User (`roles/aiplatform.user`)**:
  * Required by the dashboard runtime service account (e.g. default Compute Service Account `<YOUR_PROJECT_NUMBER>-compute@developer.gserviceaccount.com`) to query user sessions and resume running agents.
  * Required by the `pubsub-invoker` service account to trigger agent executions via Vertex AI API.
* **Pub/Sub Publisher (`roles/pubsub.publisher`)**:
  * Required by the Pub/Sub system service agent (`service-<YOUR_PROJECT_NUMBER>@gcp-sa-pubsub.iam.gserviceaccount.com`) on the dead-letter topic to route failed events.

### 4. Configuration Variables (.env)
A set of environmental variables controls the behavior of both services. Create a `.env` file from the template:
```bash
cp .env.template .env
```
| Key | Purpose | Expected Value |
| --- | --- | --- |
| `SESSION_SERVICE_URI` | Configures storage backend. | `sqlite:///shared_sessions.db` (local) or `agentengine://` (Vertex AI cloud) |
| `AGENT_RUNTIME_ID` | Identifies reasoning engine resource. | `projects/<project_num>/locations/us-east1/reasoningEngines/<engine_id>` |
| `GOOGLE_CLOUD_PROJECT` | Active GCP project. | E.g. `gen-lang-client-0513235234` |
| `GOOGLE_CLOUD_LOCATION` | Vertex AI model location. | Set to `global` (needed for `gemini-3.1-flash-lite` regional availability) |

---

## 🚀 Quick Start

### 1. Install Dependencies
Initialize the virtual environment and fetch all packages:
```bash
make install
```

### 2. Run Both Services Locally (Offline SQLite Mode)
Run the agent backend (port 8080) and manager dashboard (port 8081) concurrently, using a local SQLite database to persist sessions and test approvals:
```bash
make run-all-local
```

### 3. Run Manager Dashboard Only (Toggled by Environment)
You can launch the dashboard independently, configured to read/write to a specific environment target:
* **Local SQLite mode**: `make fe-local`
* **Staging Cloud (Vertex AI)**: `make fe-staging`
* **Production Cloud (Vertex AI)**: `make fe-production`

### 4. Test the Reasoning Engine Agent Individually
Launch the local agent playground to execute test prompts interactively:
```bash
make playground
```

### 5. Run Unit and Integration Tests
Validate your logic by running the test suite:
```bash
make test
```

### 6. Run Agent Evaluations
Generate traces and grade them using the evaluation loop:
```bash
make generate-traces
make grade
```

---

## 📖 Additional Documentation

Refer to the following guides under the `docs/` folder for deeper technical references:

* **[Deployment & Operations Guide](docs/deployment_operations.md)**: Details on standard CLI commands, manual/automated deployments, CI/CD pipelines, WIF authentication flow, and Pub/Sub setup/cleanup commands.
* **[GCP Deployment Architecture](docs/gcp_deployment_architecture.md)**: Cloud services mapping (AWS equivalent), IAM roles & service accounts config, and privilege escalation prevention.
* **[Troubleshooting Guide](docs/troubleshooting.md)**: Solutions for Pub/Sub subscription connection/OIDC issues and dashboard SQLite `user_id` state sync mismatches.

---

## 🔍 Observability

Built-in telemetry automatically exports to Cloud Trace, BigQuery, and Cloud Logging when running in the cloud.


