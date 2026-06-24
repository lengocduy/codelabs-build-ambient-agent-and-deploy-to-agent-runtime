# Manager Expense Approval Dashboard

A standalone dashboard service designed for financial managers to monitor pending expense claims, review AI-generated risk analyses, and approve or reject claims requiring manual intervention.

---

## Project Structure

```text
submission_frontend/
├── docs/                      # Documentation assets and supplementary guides
│   └── walkthrough.md         # Walkthrough specific to frontend operations
├── Dockerfile                 # Container configuration for dashboard deployment
├── main.py                    # FastAPI application, UI layouts, and session services
├── pyproject.toml             # Python packages and configuration for the service
└── README.md                  # This file
```

---

## Architecture Overview

The dashboard is built on **FastAPI** and integrates with the **Google Agent Development Kit (ADK)** to manage and resume agent sessions. 

### 1. Unified Session Handling
The app automatically resolves the appropriate ADK `SessionService` based on environment configurations:
*   **Local Offline Storage (`SqliteSessionService`)**: Reads and writes to a shared SQLite database (`shared_sessions.db`). Ideal for full offline testing.
*   **Cloud Agent Runtime (`VertexAiSessionService`)**: Connects to the reasoning engine deployed on Google Cloud Vertex AI to query active user sessions and history.

### 2. Manual Interrupt Resumptions
When an expense is at or above the approval threshold (e.g. $100) or contains security concerns, the agent pauses execution and yields a `RequestInput` event with the ID `human_approval`. 

The dashboard handles this by sending a structured resumption payload back to the reasoning engine:
```json
{
  "role": "user",
  "parts": [
    {
      "function_response": {
        "id": "<interrupt_id>",
        "name": "adk_request_input",
        "response": {
          "approved": true,
          "human_approval": "approve"
        }
      }
    }
  ]
}
```

---

## Configuration

The dashboard determines its behavior by reading configuration keys from `.env` files or environment variables:

| Variable | Description | Example / Recommended Value |
|----------|-------------|----------------------------|
| `SESSION_SERVICE_URI` | Determines storage mode. SQLite path or cloud URI. | `sqlite:///shared_sessions.db` (local) or `agentengine://` (cloud) |
| `AGENT_RUNTIME_ID` | Resource URI for the cloud reasoning engine. | `projects/<project-number>/locations/us-east1/reasoningEngines/<engine-id>` |
| `GOOGLE_CLOUD_PROJECT` | Target GCP project identifier. | `<YOUR_PROJECT_ID>` |
| `GOOGLE_CLOUD_LOCATION` | Vertex AI API query location endpoint. | `global` |

---

## How to Run Locally

For convenience, several targets are defined in the root [Makefile](file:///Volumes/Investor/Learning/Google%205-Day%20AI%20Agents%20Intensive%20Course/ambient-expense-agent/Makefile):

### 1. Run Backend & Frontend Concurrently (Offline SQLite Mode)
Starts both the agent backend (port 8080) and the dashboard frontend (port 8081), writing to the same SQLite database.
```bash
make run-all-local
```

### 2. Run Dashboard Only (Local SQLite Mode)
```bash
make fe-local
```

### 3. Run Dashboard Only (Connected to Staging Cloud)
```bash
make fe-staging
```

### 4. Run Dashboard Only (Connected to Production Cloud)
```bash
make fe-production
```

---

## Cloud Run Deployment

The dashboard is deployed on Cloud Run as `expense-manager-dashboard`.

### 1. Build and Deploy
The container is built from the project root (to include the `expense_agent` package dependency) and deployed to `us-east1` with unauthenticated invocations allowed:
```bash
gcloud run deploy expense-manager-dashboard \
  --source . \
  --region us-east1 \
  --project <YOUR_PROJECT_ID> \
  --set-env-vars="GOOGLE_CLOUD_PROJECT=<YOUR_PROJECT_ID>,AGENT_RUNTIME_ID=projects/<YOUR_PROJECT_NUMBER>/locations/us-east1/reasoningEngines/<YOUR_REASONING_ENGINE_ID>" \
  --allow-unauthenticated \
  --memory=1Gi
```

### 2. Resource Allocation
*   **Memory**: Set to **`1Gi`** (`1024 MiB`) to prevent memory exhaustion (error 503) when importing large Vertex AI / Google GenAI dependencies.

### 3. IAM Role Bindings
The Cloud Run service account must be granted the `roles/aiplatform.user` role so it has permission to query sessions and resume running agents:
```bash
gcloud projects add-iam-policy-binding <YOUR_PROJECT_ID> \
  --member="serviceAccount:<YOUR_PROJECT_NUMBER>-compute@developer.gserviceaccount.com" \
  --role="roles/aiplatform.user"
```
