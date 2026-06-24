# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
import os
import logging
import base64
import json

from fastapi import FastAPI, Request
from google.adk.cli.fast_api import get_fast_api_app
from google.adk.runners import Runner
from google.adk.agents.run_config import RunConfig, StreamingMode
from google.genai import types
from dotenv import load_dotenv

from expense_agent.app_utils.telemetry import setup_telemetry
from expense_agent.app_utils.typing import Feedback

# Load env variables from .env if present
load_dotenv()

# Configure standard Python logging for console logs
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("expense_agent")

setup_telemetry()

allow_origins = (
    os.getenv("ALLOW_ORIGINS", "").split(",") if os.getenv("ALLOW_ORIGINS") else None
)

# Artifact bucket for ADK (created by Terraform, passed via env var)
logs_bucket_name = os.environ.get("LOGS_BUCKET_NAME")

AGENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Read session configuration from env variable (defaulting to None / local storage)
session_service_uri = os.environ.get("SESSION_SERVICE_URI")

artifact_service_uri = f"gs://{logs_bucket_name}" if logs_bucket_name else None

app: FastAPI = get_fast_api_app(
    agents_dir=AGENT_DIR,
    web=True,
    artifact_service_uri=artifact_service_uri,
    allow_origins=allow_origins,
    session_service_uri=session_service_uri,
    otel_to_cloud=False,  # Telemetry: Set otel_to_cloud=False
)
app.title = "ambient-expense-agent"
app.description = "API for interacting with the Agent ambient-expense-agent"


def get_adk_server(app_inst: FastAPI):
    """Reflectively extract ApiServer/DevServer instance from route closures."""
    for route in app_inst.routes:
        if not hasattr(route, "endpoint") or not route.endpoint:
            continue
        func = route.endpoint
        if not hasattr(func, "__closure__") or not func.__closure__:
            continue
        for cell in func.__closure__:
            try:
                val = cell.cell_contents
                if val.__class__.__name__ in ("ApiServer", "DevServer"):
                    return val
            except Exception:
                pass
    return None


@app.post("/")
async def handle_pubsub(request: Request):
    """Ambient event-driven endpoint that accepts Pub/Sub push messages."""
    logger.info("Received request on POST /")
    try:
        body = await request.json()
    except Exception as e:
        logger.error(f"Failed to parse JSON body: {e}")
        return {"status": "error", "message": "Invalid JSON body"}

    logger.info(f"Incoming event payload: {body}")

    # Extract and normalize subscription path
    subscription_path = body.get("subscription")
    if subscription_path:
        subscription_short_name = subscription_path.split("/")[-1]
    else:
        subscription_short_name = "default-subscription"

    logger.info(f"Normalized subscription short name: {subscription_short_name}")

    # Resolve shared ApiServer/DevServer to access stateful session storage
    adk_server = get_adk_server(app)
    if not adk_server:
        logger.error("Failed to find ApiServer/DevServer instance from FastAPI app")
        return {"status": "error", "message": "Server initialization error"}

    session_service = adk_server.session_service
    runner = await adk_server.get_runner_async(app_name="expense_agent")

    user_id = "ambient_system"
    session_id = subscription_short_name

    # Check if a session already exists for this subscription; if not, create it.
    session = await session_service.get_session(app_name="expense_agent", user_id=user_id, session_id=session_id)
    if not session:
        logger.info(f"Creating new session: {session_id} for user {user_id}")
        session = await session_service.create_session(app_name="expense_agent", user_id=user_id, session_id=session_id)
    else:
        logger.info(f"Retrieved existing session: {session_id} for user {user_id}")

    # Feed payload into the runner using ADK 2.0 streaming mode
    message = types.Content(
        role="user",
        parts=[types.Part.from_text(text=json.dumps(body))]
    )

    logger.info(f"Executing workflow for session {session_id}...")
    events = runner.run(
        new_message=message,
        user_id=user_id,
        session_id=session.id,
        run_config=RunConfig(streaming_mode=StreamingMode.SSE),
    )

    is_paused = False
    pending_message = ""
    final_output = None

    for event in events:
        if event.long_running_tool_ids and "human_approval" in event.long_running_tool_ids:
            is_paused = True
            if event.content and event.content.parts:
                for part in event.content.parts:
                    if part.function_call and part.function_call.name == "adk_request_input":
                        pending_message = part.function_call.args.get("message", "")
        if event.output:
            final_output = event.output

    if is_paused:
        logger.info(f"Workflow paused for human approval on session {session_id}")
        return {
            "status": "paused",
            "session_id": session_id,
            "message": pending_message
        }
    elif final_output is not None:
        logger.info(f"Workflow completed successfully on session {session_id}. Output: {final_output}")
        return {
            "status": "completed",
            "session_id": session_id,
            "output": final_output
        }
    else:
        logger.info(f"Workflow finished without final output for session {session_id}")
        return {
            "status": "running",
            "session_id": session_id
        }


@app.post("/feedback")
def collect_feedback(feedback: Feedback) -> dict[str, str]:
    """Collect and log feedback."""
    logger.info(f"Feedback: {feedback.model_dump()}")
    return {"status": "success"}


# Main execution
if __name__ == "__main__":
    import uvicorn
    # Serves on port 8080 by default for ambient event processing
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
