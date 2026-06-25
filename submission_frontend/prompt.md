# prompt 

Keep track the prompts to create this agent

## Prompt 1: Setup frontend

```text
Vibe-code a standalone manager-dashboard service in a new folder
"submission_frontend/". I want:

  - A FastAPI service with the following endpoints:
    1. GET /: Serves a beautiful, interactive manager dashboard HTML page. Use Outfit or Inter Google Fonts, sleek glassmorphism styling (dark background, radial glows, cards with backdrop blurs and subtle borders). It should fetch pending approvals from the backend and display them as interactive cards.
    2. GET /api/pending: Queries the ADK VertexAiSessionService to list all sessions, fetches the full history for each session, and identifies unresolved `adk_request_input` function call events (events requesting input that do not have a corresponding `adk_request_input` function response event). Returns the session ID, interrupt ID, and expense payload details.
    3. POST /api/action/{session_id}: Resumes the paused session on Agent Runtime. To avoid duplicate parameter errors on the ADK runner, pass the resume payload (with role: user and parts: [function_response: {id: interrupt_id, name: adk_request_input, response: {approved: True/False}}]) directly as the dict value of the `message` argument to the SDK. Also make sure to set the `user_id` strictly to "default-user" to avoid session ownership mismatch errors.
  - Read the GCP project and AGENT_RUNTIME_ID from environment variables.

  - A pyproject.toml with fastapi, uvicorn, google-adk, and google-cloud-aiplatform.

Make sure the UI looks highly polished and premium (colors, transitions, interactive approve/reject actions with loading spinners, and a modal that slides out to display the agent's final compliance review). Show me the main.py implementation when done.
```

## Prompt 2: Deploy the Dashboard to Cloud Run

```text
Deploy the submission_frontend folder as "expense-manager-dashboard" to Cloud Run. Pass
GOOGLE_CLOUD_PROJECT, and AGENT_RUNTIME_ID as environment variables, and configure the deployment to allow unauthenticated invocations so it is publicly reachable. After it deploys, grant the dashboard's runtime service account the necessary roles on the project so it can resume the Agent
Runtime agent and query its sessions. Print the Dashboard URL when done.
```

## Prompt 3: Retrieve the Dashboard URL

```text
What is the live HTTPS URL of the deployed "expense-manager-dashboard" Cloud Run service?
```