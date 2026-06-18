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