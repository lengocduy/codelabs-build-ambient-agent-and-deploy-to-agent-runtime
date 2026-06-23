# prompt 

Keep track the prompts to create this agent

## Agent's prompts

### Prompt 1: Create the project scaffolding

```text
Create a new directory called "ambient-expense-agent", initialize it with the ADK
starter template and tell me when it is ready.
```

### Prompt 2: Set up credentials and graph API

```text
Load your adk-cheatsheet, adk-scaffold, and google-agents-cli-workflow skills and
confirm they're active. For this project we use ADK 2.0 (google-adk>=2.0.0a0), so
use the new graph Workflow API (function nodes, edges, and RequestInput for the
human-in-the-loop step), not the 1.x SequentialAgent / LlmAgent style. Then set up
local authentication in a .env file — I'll use either a Google AI Studio API key
or my own Google Cloud project; configure whichever applies and tell
me if there's a gcloud command I need to run and also where to obtain the API keys from.
```

### Prompt 3: Build the stateful graph core

The routing rules:
- `< $100` → `auto_approve` (a plain function node, no LLM).
- `>= $100` → `an LLM review_agent` analyzes risk, then a human-in-the-loop node pauses the workflow for a human via ADK 2.0's RequestInput.

```text
I'm building an ambient expense-approval agent as an ADK 2.0 graph workflow — use
the new Workflow graph API (function nodes wired together by edges, with
RequestInput for the human-in-the-loop step), not the 1.x SequentialAgent /
LlmAgent style.

Here's the behavior I want:
An expense report arrives as a JSON event — the
details sit under a "data" key that might be base64-encoded (real Pub/Sub) or
plain JSON (local testing). The agent pulls out the expense (amount, submitter,
category, description, date), then applies one rule:
  - Under $100 → auto-approve instantly, no LLM involved.
  - $100 or more → an LLM reviews it for risk factors and raises an alert, then
    the workflow pauses for a human to approve or reject; once they decide,
    record the outcome.

Keep the dollar threshold and the routing in python code — the model is only there
for the risk judgment. Put the threshold and the model (gemini-3.1-flash-lite)
in a config, and the agent under expense_agent/.  Then walk me through the graph
you wired up step by step, highlighing the code I should be paying attention to.
```

### Prompt 4: Add security - PII redaction & prompt-injection defense

```text
Let's add security controls to the graph. Before any expense reaches the LLM
reviewer, add a security checkpoint to the graph that does
two things:

  1. Scrub personal data from the description — SSNs and credit-card numbers must
     never reach the model or the logs, and the human-approval payload should be
     clean too. Remember which categories you redacted.
  2. Defend against prompt injection — if the description is stuffed with
     instructions trying to force an auto-approval or bypass the rules, don't let
     the model see it at all: route it straight to a human for review and flag it
     as a security event.

Clean expenses should continue on to the LLM reviewer. Show me how this checkpoint
slots into the graph.
```

### Prompt 5: Simplify local development setup

```text
Give me a Makefile (install, open the playground) and a pyproject.toml so I
can run everything locally on ADK 2.0. Install dependencies, then run
"make playground" in the background to launch the UI. Once the playground is
running, send the following test expense payload to verify the workflow:

{"amount": 150.0, "submitter": "alice@company.com", "category": "software", "description": "IDE License", "date": "2026-06-06"}

Explain how I can check the UI to observe the human-in-the-loop flow.
```

### Prompt 6: Make it ambient event-driven AI agent

```text
Make this agent ambient so events drive it instead of a chat. Stand it up as a
local web service that accepts Pub/Sub trigger messages and feeds each one into
the workflow, serving on port 8080. One gotcha to handle: Pub/Sub sends a
fully-qualified subscription path, so normalize it down to a short name to keep
session records readable. Verify the existing pyproject.toml to ensure fastapi is configured, and tell me how to run the makefile.

Follow this concise developer checklist for the app implementation:
- Telemetry: Set otel_to_cloud=False
- Logging: Use standard Python logging for console logs.

Explain the changes you make.
```

### Prompt 7: Evaluate the agent

```text
Let's set up and execute local evaluations for our expense agent. Please perform the
following steps:

1. Create a synthetic evaluation dataset of 5 diverse expense scenarios in
   `tests/eval/datasets/basic-dataset.json` (spanning auto-approvals, high-value
   manual approvals, PII leaks, and prompt injections). You decide what the specific
   scenarios should be to test our agent's rules.
2. Write a trace generator script `tests/eval/generate_traces.py` that runs the
   scenarios through the local ADK workflow runner. Ensure it intercepts human-in-the-loop
   approval steps and automates decisions (approves clean requests, rejects prompt
   injections) before serializing traces into `artifacts/traces/generated_traces.json`.
3. Configure `tests/eval/eval_config.yaml` with two custom LLM-as-judge metrics:
   - One judges routing correctness: under $100 is auto-approved, $100 or more goes to a human and
     is never auto-approved. 
   - The other judges security containment: PII is redacted before the model sees it, and       injection attempts are escalated to a human with the model bypassed and never auto-approved (a clean expense passes trivially). Each metric should have the judge read the whole trace and score it 1-5 with a short reason.`
4. Add agents-cli `generate-traces` and `grade` targets to the `Makefile`.
5. Execute the trace generator and the agents-cli grading tool to run the evaluation,
   and present the final summary table and per-case explanations to me.
```

### Prompt 8: Set up Google Cloud Environment to deploy to Agent Runtime

Agent Runtime is a fully managed Google Cloud service that lets you deploy, manage, and scale AI agents in production. Agent Runtime handles the operational complexities of hosting, offering a stateful environment with features like session management, long-term memory, and secure code execution sandboxes.

```text
Help me set up my Google Cloud environment. Connect to my project
`YOUR_PROJECT_ID` in the global region, authenticate, and enable the necessary
generative platform APIs (aiplatform.googleapis.com, cloudtrace.googleapis.com,
cloudbuild.googleapis.com, agentregistry.googleapis.com).
```

> Replace `YOUR_PROJECT_ID` with your actual Google Cloud Project ID.

### Prompt 9: Prepare for Production Deployment

```text
Scaffold the production deployment files for Agent Runtime.
```

### Prompt 10: Packaging and Local Verification

```text
Lock my python dependencies and run a dry-run deployment to check for any
configuration or dependency issues.
```

### Prompt 11: Deploy to Agent Runtim

```text
Deploy this agent to Agent Runtime.
```

### Prompt 12: Test the production deployment

```text
Test my deployed Agent Runtime engine with two test cases: first a standard
meal expense of $50 to verify automatic approval, and second, a client dinner
expense of $150 to verify that the human-in-the-loop pause is triggered.
```

### Prompt 13: Clean up the deployment to prevent incurring charges

```text
Clean up all my deployed cloud resources. Use the Agent Runtime ID from
deployment_metadata.json to delete the engine from Vertex AI, remove the local
deployment_metadata.json file, and delete the container image repository from
Artifact Registry.
```

## Frontend's Prompts

### Prompt 1: Setup frontend

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