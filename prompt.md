# prompt 

Keep track the prompts to create this agent

## Prompt 1: Create the project scaffolding

```text
Create a new directory called "ambient-expense-agent", initialize it with the ADK
starter template and tell me when it is ready.
```

## Prompt 2: Set up credentials and graph API

```text
Load your adk-cheatsheet, adk-scaffold, and google-agents-cli-workflow skills and
confirm they're active. For this project we use ADK 2.0 (google-adk>=2.0.0a0), so
use the new graph Workflow API (function nodes, edges, and RequestInput for the
human-in-the-loop step), not the 1.x SequentialAgent / LlmAgent style. Then set up
local authentication in a .env file — I'll use either a Google AI Studio API key
or my own Google Cloud project; configure whichever applies and tell
me if there's a gcloud command I need to run and also where to obtain the API keys from.
```

## Prompt 3: Build the stateful graph core

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

## Prompt 4: Add security - PII redaction & prompt-injection defense

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