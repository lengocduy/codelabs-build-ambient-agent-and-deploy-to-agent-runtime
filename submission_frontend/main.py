import os
import re
import logging
import json
from typing import Optional, Any, List
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

# Try importing from the target agent module. During standalone runs, this ensures
# the agent and config modules are fully imported and resolved.
try:
    from expense_agent.agent import root_agent
except ImportError:
    try:
        from app.agent import root_agent
    except ImportError:
        root_agent = None

from google.adk.sessions.vertex_ai_session_service import VertexAiSessionService
from google.adk.runners import Runner
from google.adk.agents.run_config import RunConfig, StreamingMode
from google.genai import types

# Configure Logger
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("manager_dashboard")

app = FastAPI(title="Manager Expense Approval Dashboard")

# Read configurations
project_id = os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("GCP_PROJECT")
agent_runtime_id = os.environ.get("AGENT_RUNTIME_ID")
location = os.environ.get("GOOGLE_CLOUD_LOCATION") or "us-east1"

class ActionPayload(BaseModel):
    approved: bool
    interrupt_id: str

@app.get("/api/pending")
async def get_pending_approvals():
    """Queries the ADK VertexAiSessionService to list all sessions, fetches the full history,

    and identifies unresolved adk_request_input function call events.
    """
    current_runtime_id = os.environ.get("AGENT_RUNTIME_ID") or agent_runtime_id
    current_project = os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("GCP_PROJECT") or project_id
    current_location = os.environ.get("GOOGLE_CLOUD_LOCATION") or location

    if not current_runtime_id:
        # Fallback to check local metadata file
        metadata_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "deployment_metadata.json")
        if os.path.exists(metadata_path):
            try:
                with open(metadata_path, "r") as f:
                    meta = json.load(f)
                    current_runtime_id = meta.get("remote_agent_runtime_id")
            except Exception as e:
                logger.error(f"Failed to read deployment_metadata.json fallback: {e}")

    if not current_runtime_id:
        return {
            "status": "error",
            "message": "AGENT_RUNTIME_ID environment variable is not configured.",
            "details": "Please set AGENT_RUNTIME_ID or deploy the engine to populate deployment_metadata.json."
        }

    # Extract resource components
    engine_id = current_runtime_id
    parsed_project = current_project
    parsed_location = current_location

    match = re.match(
        r"^projects/([^/]+)/locations/([^/]+)/reasoningEngines/([^/]+)$",
        current_runtime_id.strip()
    )
    if match:
        parsed_project = match.group(1)
        parsed_location = match.group(2)
        engine_id = match.group(3)

    logger.info(f"Listing sessions for Engine: {engine_id} in project: {parsed_project}, location: {parsed_location}")

    try:
        session_service = VertexAiSessionService(
            project=parsed_project,
            location=parsed_location,
            agent_engine_id=engine_id
        )

        list_res = await session_service.list_sessions(app_name="expense_agent")
        pending_items = []

        for s in list_res.sessions:
            try:
                # Fetch full session with event history
                fs = await session_service.get_session(
                    app_name="expense_agent",
                    user_id=s.user_id,
                    session_id=s.id
                )
                if not fs or not fs.events:
                    continue

                # Find all adk_request_input calls and responses
                calls = {}
                responses = set()

                for event in fs.events:
                    for call in event.get_function_calls():
                        if call.name == "adk_request_input":
                            calls[call.id] = call
                    for resp in event.get_function_responses():
                        if resp.name == "adk_request_input":
                            responses.add(resp.id)

                unresolved_call = None
                for cid, call in calls.items():
                    if cid not in responses:
                        unresolved_call = call
                        break

                if unresolved_call:
                    # Found unresolved manual input request
                    details = {
                        "session_id": s.id,
                        "interrupt_id": unresolved_call.id,
                        "submitter": "Unknown",
                        "amount": 0.0,
                        "category": "Unknown",
                        "description": "No description provided",
                        "date": "Unknown",
                        "raw_message": "",
                        "risk_rating": "Unknown",
                        "risk_factors": [],
                        "explanation": "",
                        "is_security_event": False
                    }

                    # Parse from user's original message
                    for event in fs.events:
                        if event.author == "user" and event.content:
                            for part in event.content.parts:
                                if part.text:
                                    try:
                                        payload = json.loads(part.text)
                                        data = payload.get("data", payload)
                                        if isinstance(data, dict):
                                            details["submitter"] = data.get("submitter", details["submitter"])
                                            details["amount"] = data.get("amount", details["amount"])
                                            details["category"] = data.get("category", details["category"])
                                            details["description"] = data.get("description", details["description"])
                                            details["date"] = data.get("date", details["date"])
                                    except Exception:
                                        pass
                                    break
                            break

                    # Extract details from unresolved function call args
                    if unresolved_call.args:
                        msg = unresolved_call.args.get("message", "")
                        details["raw_message"] = msg
                        details["is_security_event"] = "SECURITY ALERT" in msg or "🚨" in msg

                        # Parse using regex matching from the LLM formatted message
                        if "Risk Rating:" in msg:
                            m_rating = re.search(r"Risk Rating:\s*([^\n]+)", msg, re.IGNORECASE)
                            if m_rating:
                                details["risk_rating"] = m_rating.group(1).strip()
                        
                        if "Risk Factors:" in msg:
                            m_factors = re.search(r"Risk Factors:\s*([^\n]+)", msg, re.IGNORECASE)
                            if m_factors:
                                factors_str = m_factors.group(1).strip()
                                details["risk_factors"] = [f.strip() for f in factors_str.split(",") if f.strip() and f.strip().lower() != "none"]

                        if "Explanation:" in msg:
                            m_exp = re.search(r"Explanation:\s*(.+?)(?=\n\n|\Z)", msg, re.DOTALL | re.IGNORECASE)
                            if m_exp:
                                details["explanation"] = m_exp.group(1).strip()

                    pending_items.append(details)

            except Exception as se:
                logger.error(f"Error fetching session {s.id}: {se}", exc_info=True)

        return {"status": "success", "pending": pending_items}

    except Exception as e:
        logger.error(f"Error listing sessions: {e}", exc_info=True)
        return {
            "status": "error",
            "message": f"Failed to list sessions from Vertex AI: {str(e)}",
            "details": "Make sure your GCP credentials are valid and the Reasoning Engine / Agent Runtime ID is correct."
        }

@app.post("/api/action/{session_id}")
async def handle_action(session_id: str, payload: ActionPayload):
    """Resumes the paused session on Agent Runtime."""
    current_runtime_id = os.environ.get("AGENT_RUNTIME_ID") or agent_runtime_id
    current_project = os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("GCP_PROJECT") or project_id
    current_location = os.environ.get("GOOGLE_CLOUD_LOCATION") or location

    if not current_runtime_id:
        metadata_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "deployment_metadata.json")
        if os.path.exists(metadata_path):
            try:
                with open(metadata_path, "r") as f:
                    meta = json.load(f)
                    current_runtime_id = meta.get("remote_agent_runtime_id")
            except Exception:
                pass

    if not current_runtime_id:
        raise HTTPException(status_code=500, detail="AGENT_RUNTIME_ID environment variable is not configured.")

    engine_id = current_runtime_id
    parsed_project = current_project
    parsed_location = current_location

    match = re.match(
        r"^projects/([^/]+)/locations/([^/]+)/reasoningEngines/([^/]+)$",
        current_runtime_id.strip()
    )
    if match:
        parsed_project = match.group(1)
        parsed_location = match.group(2)
        engine_id = match.group(3)

    if not root_agent:
        raise HTTPException(status_code=500, detail="root_agent not loaded from expense_agent package.")

    try:
        session_service = VertexAiSessionService(
            project=parsed_project,
            location=parsed_location,
            agent_engine_id=engine_id
        )

        runner = Runner(
            agent=root_agent,
            session_service=session_service,
            app_name="expense_agent"
        )

        # To avoid duplicate parameter errors on the ADK runner, pass the resume payload directly as the dict value of the message argument:
        message_payload = {
            "role": "user",
            "parts": [
                {
                    "function_response": {
                        "id": payload.interrupt_id,
                        "name": "adk_request_input",
                        "response": {
                            "approved": payload.approved,
                            "human_approval": "approve" if payload.approved else "reject"
                        }
                    }
                }
            ]
        }

        # Set user_id strictly to "default-user" to avoid session ownership mismatch errors
        logger.info(f"Resuming session {session_id} for user default-user with payload: {message_payload}")
        
        events = runner.run(
            user_id="default-user",
            session_id=session_id,
            new_message=message_payload,
            run_config=RunConfig(streaming_mode=StreamingMode.SSE)
        )

        final_output = None
        outputs = []
        for event in events:
            if event.output:
                final_output = event.output
            if event.content and event.content.parts:
                for part in event.content.parts:
                    if part.text:
                        outputs.append(part.text)

        return {
            "status": "success",
            "final_output": final_output,
            "outputs": outputs
        }

    except Exception as e:
        logger.error(f"Error resuming session {session_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/", response_class=HTMLResponse)
async def get_dashboard():
    """Serves the dashboard HTML page with glassmorphism styling."""
    html_content = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Expense Manager Dashboard</title>
        <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700&display=swap" rel="stylesheet">
        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
        <style>
            :root {
                --primary: #6366f1;
                --primary-glow: rgba(99, 102, 241, 0.15);
                --accent: #a855f7;
                --accent-glow: rgba(168, 85, 247, 0.15);
                --bg: #070913;
                --glass-bg: rgba(255, 255, 255, 0.03);
                --glass-border: rgba(255, 255, 255, 0.07);
                --text: #f3f4f6;
                --text-muted: #9ca3af;
                --emerald: #10b981;
                --emerald-glow: rgba(16, 185, 129, 0.2);
                --rose: #ef4444;
                --rose-glow: rgba(239, 68, 68, 0.2);
            }

            * {
                box-sizing: border-box;
                margin: 0;
                padding: 0;
            }

            body {
                background-color: var(--bg);
                background-image:
                    radial-gradient(circle at 10% 20%, var(--primary-glow) 0%, transparent 40%),
                    radial-gradient(circle at 90% 80%, var(--accent-glow) 0%, transparent 40%);
                color: var(--text);
                font-family: 'Outfit', sans-serif;
                min-height: 100vh;
                display: flex;
                flex-direction: column;
                overflow-x: hidden;
            }

            header {
                background: rgba(15, 23, 42, 0.4);
                backdrop-filter: blur(16px);
                -webkit-backdrop-filter: blur(16px);
                border-bottom: 1px solid rgba(255, 255, 255, 0.05);
                padding: 20px 40px;
                display: flex;
                justify-content: space-between;
                align-items: center;
                position: sticky;
                top: 0;
                z-index: 100;
            }

            .logo {
                display: flex;
                align-items: center;
                gap: 12px;
                font-size: 22px;
                font-weight: 700;
                letter-spacing: 0.5px;
                background: linear-gradient(135deg, var(--primary), var(--accent));
                -webkit-background-clip: text;
                -webkit-text-fill-color: transparent;
            }

            .logo i {
                background: linear-gradient(135deg, var(--primary), var(--accent));
                -webkit-background-clip: text;
                -webkit-text-fill-color: transparent;
            }

            .system-status {
                display: flex;
                align-items: center;
                gap: 8px;
                font-size: 14px;
                color: var(--text-muted);
                background: rgba(255, 255, 255, 0.05);
                padding: 6px 14px;
                border-radius: 9999px;
                border: 1px solid var(--glass-border);
            }

            .status-indicator {
                width: 8px;
                height: 8px;
                background-color: var(--emerald);
                border-radius: 50%;
                box-shadow: 0 0 8px var(--emerald);
            }
            
            .status-indicator.error {
                background-color: var(--rose);
                box-shadow: 0 0 8px var(--rose);
            }

            .container {
                max-width: 1200px;
                margin: 40px auto;
                padding: 0 20px;
                flex: 1;
                width: 100%;
            }

            .dashboard-title-area {
                margin-bottom: 30px;
                display: flex;
                justify-content: space-between;
                align-items: center;
            }

            .dashboard-title-area h1 {
                font-size: 32px;
                font-weight: 700;
                background: linear-gradient(to right, #ffffff, #d1d5db);
                -webkit-background-clip: text;
                -webkit-text-fill-color: transparent;
            }

            .btn-refresh {
                background: var(--glass-bg);
                border: 1px solid var(--glass-border);
                color: var(--text);
                padding: 10px 20px;
                border-radius: 12px;
                cursor: pointer;
                display: flex;
                align-items: center;
                gap: 8px;
                font-size: 14px;
                font-weight: 500;
                transition: all 0.2s ease;
            }

            .btn-refresh:hover {
                background: rgba(255, 255, 255, 0.08);
                border-color: rgba(255, 255, 255, 0.2);
            }

            /* Error / Config alert banner */
            .alert-banner {
                background: rgba(239, 68, 68, 0.07);
                border: 1px solid rgba(239, 68, 68, 0.15);
                border-radius: 16px;
                padding: 20px;
                margin-bottom: 30px;
                display: none;
                align-items: flex-start;
                gap: 16px;
            }

            .alert-banner i {
                color: var(--rose);
                font-size: 24px;
                margin-top: 2px;
            }

            .alert-content h3 {
                color: #fca5a5;
                font-size: 16px;
                font-weight: 600;
                margin-bottom: 4px;
            }

            .alert-content p {
                color: #f87171;
                font-size: 14px;
                line-height: 1.5;
            }

            .grid {
                display: grid;
                grid-template-columns: repeat(auto-fill, minmax(350px, 1fr));
                gap: 28px;
            }

            .card {
                background: var(--glass-bg);
                backdrop-filter: blur(16px);
                -webkit-backdrop-filter: blur(16px);
                border: 1px solid var(--glass-border);
                border-radius: 20px;
                padding: 24px;
                display: flex;
                flex-direction: column;
                justify-content: space-between;
                position: relative;
                overflow: hidden;
                box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.2);
                transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
            }

            .card::before {
                content: '';
                position: absolute;
                top: 0;
                left: 0;
                width: 100%;
                height: 4px;
                background: linear-gradient(90deg, var(--primary), var(--accent));
                opacity: 0.7;
            }

            .card.security-alert::before {
                background: var(--rose);
            }

            .card:hover {
                transform: translateY(-6px);
                border-color: rgba(255, 255, 255, 0.15);
                box-shadow: 0 15px 45px rgba(0, 0, 0, 0.4), 0 0 25px var(--primary-glow);
            }

            .card.security-alert:hover {
                box-shadow: 0 15px 45px rgba(0, 0, 0, 0.4), 0 0 25px rgba(239, 68, 68, 0.15);
            }

            .card-header {
                display: flex;
                justify-content: space-between;
                align-items: flex-start;
                margin-bottom: 18px;
            }

            .card-header .amount {
                font-size: 24px;
                font-weight: 700;
                color: #ffffff;
            }

            .badge {
                display: inline-flex;
                align-items: center;
                padding: 4px 10px;
                border-radius: 9999px;
                font-size: 11px;
                font-weight: 600;
                text-transform: uppercase;
                letter-spacing: 0.5px;
            }

            .badge-low {
                background: rgba(16, 185, 129, 0.1);
                color: #34d399;
                border: 1px solid rgba(16, 185, 129, 0.2);
            }

            .badge-medium {
                background: rgba(245, 158, 11, 0.1);
                color: #fbbf24;
                border: 1px solid rgba(245, 158, 11, 0.2);
            }

            .badge-high {
                background: rgba(239, 68, 68, 0.1);
                color: #f87171;
                border: 1px solid rgba(239, 68, 68, 0.2);
            }

            .badge-security {
                background: rgba(239, 68, 68, 0.2);
                color: #ef4444;
                border: 1px solid rgba(239, 68, 68, 0.4);
                display: flex;
                align-items: center;
                gap: 4px;
            }

            .card-body {
                margin-bottom: 24px;
            }

            .meta-item {
                display: flex;
                justify-content: space-between;
                margin-bottom: 10px;
                font-size: 14px;
            }

            .meta-label {
                color: var(--text-muted);
            }

            .meta-value {
                color: #e5e7eb;
                font-weight: 500;
            }

            .card-description {
                font-size: 14px;
                color: var(--text-muted);
                background: rgba(255, 255, 255, 0.02);
                padding: 12px;
                border-radius: 10px;
                border: 1px solid rgba(255, 255, 255, 0.04);
                margin-top: 14px;
                line-height: 1.4;
            }

            .btn-group {
                display: grid;
                grid-template-columns: 1fr 1fr;
                gap: 12px;
            }

            .btn {
                font-family: inherit;
                padding: 12px 16px;
                border-radius: 12px;
                font-size: 14px;
                font-weight: 600;
                cursor: pointer;
                display: flex;
                align-items: center;
                justify-content: center;
                gap: 8px;
                transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
            }

            .btn-approve {
                background: linear-gradient(135deg, #10b981, #059669);
                color: white;
                border: none;
                box-shadow: 0 4px 14px var(--emerald-glow);
            }

            .btn-approve:hover {
                box-shadow: 0 6px 20px rgba(16, 185, 129, 0.4);
                filter: brightness(1.1);
                transform: translateY(-1px);
            }

            .btn-reject {
                background: transparent;
                color: #f87171;
                border: 1px solid rgba(239, 68, 68, 0.3);
            }

            .btn-reject:hover {
                background: rgba(239, 68, 68, 0.08);
                border-color: rgba(239, 68, 68, 0.6);
                transform: translateY(-1px);
            }

            .btn-details {
                grid-column: span 2;
                background: rgba(255, 255, 255, 0.04);
                color: #e5e7eb;
                border: 1px solid rgba(255, 255, 255, 0.08);
                margin-bottom: 12px;
            }

            .btn-details:hover {
                background: rgba(255, 255, 255, 0.08);
                border-color: rgba(255, 255, 255, 0.2);
            }

            /* Spinner and loaders */
            .spinner {
                border: 2px solid rgba(255, 255, 255, 0.1);
                width: 16px;
                height: 16px;
                border-radius: 50%;
                border-left-color: #ffffff;
                animation: spin 0.8s linear infinite;
                display: none;
            }

            @keyframes spin {
                0% { transform: rotate(0deg); }
                100% { transform: rotate(360deg); }
            }

            .btn.loading .spinner {
                display: inline-block;
            }
            .btn.loading span {
                display: none;
            }
            .btn.loading {
                pointer-events: none;
                opacity: 0.8;
            }

            /* Empty state style */
            .empty-state {
                grid-column: 1 / -1;
                display: flex;
                flex-direction: column;
                align-items: center;
                justify-content: center;
                padding: 80px 20px;
                text-align: center;
                background: var(--glass-bg);
                backdrop-filter: blur(16px);
                border-radius: 20px;
                border: 1px solid var(--glass-border);
            }

            .empty-state i {
                font-size: 54px;
                background: linear-gradient(135deg, var(--primary), var(--accent));
                -webkit-background-clip: text;
                -webkit-text-fill-color: transparent;
                margin-bottom: 20px;
                opacity: 0.6;
            }

            .empty-state h3 {
                font-size: 20px;
                font-weight: 600;
                margin-bottom: 8px;
            }

            .empty-state p {
                color: var(--text-muted);
                max-width: 400px;
                font-size: 14px;
                line-height: 1.5;
            }

            /* Modal sliding drawer from right side */
            .drawer-overlay {
                position: fixed;
                top: 0;
                left: 0;
                width: 100%;
                height: 100%;
                background: rgba(0, 0, 0, 0.6);
                backdrop-filter: blur(8px);
                -webkit-backdrop-filter: blur(8px);
                z-index: 999;
                opacity: 0;
                pointer-events: none;
                transition: opacity 0.3s ease;
            }

            .drawer-overlay.open {
                opacity: 1;
                pointer-events: auto;
            }

            .drawer {
                position: fixed;
                top: 0;
                right: -480px;
                width: 460px;
                height: 100%;
                background: rgba(11, 15, 27, 0.97);
                backdrop-filter: blur(24px);
                -webkit-backdrop-filter: blur(24px);
                border-left: 1px solid rgba(255, 255, 255, 0.08);
                box-shadow: -15px 0 45px rgba(0, 0, 0, 0.7);
                z-index: 1000;
                transition: right 0.4s cubic-bezier(0.16, 1, 0.3, 1);
                padding: 40px 30px;
                display: flex;
                flex-direction: column;
                justify-content: space-between;
            }

            .drawer.open {
                right: 0;
            }

            .drawer-header {
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 24px;
            }

            .drawer-header h2 {
                font-size: 22px;
                font-weight: 700;
                color: #ffffff;
                display: flex;
                align-items: center;
                gap: 10px;
            }

            .btn-close-drawer {
                background: transparent;
                border: none;
                color: var(--text-muted);
                font-size: 20px;
                cursor: pointer;
                width: 36px;
                height: 36px;
                border-radius: 50%;
                display: flex;
                align-items: center;
                justify-content: center;
                transition: all 0.2s ease;
            }

            .btn-close-drawer:hover {
                background: rgba(255, 255, 255, 0.05);
                color: #ffffff;
            }

            .drawer-scroll-body {
                flex: 1;
                overflow-y: auto;
                padding-right: 6px;
                margin-bottom: 20px;
            }

            /* Custom scrollbar for drawer */
            .drawer-scroll-body::-webkit-scrollbar {
                width: 6px;
            }
            .drawer-scroll-body::-webkit-scrollbar-track {
                background: transparent;
            }
            .drawer-scroll-body::-webkit-scrollbar-thumb {
                background: rgba(255, 255, 255, 0.1);
                border-radius: 99px;
            }
            .drawer-scroll-body::-webkit-scrollbar-thumb:hover {
                background: rgba(255, 255, 255, 0.2);
            }

            .section-title {
                font-size: 13px;
                font-weight: 600;
                text-transform: uppercase;
                letter-spacing: 1px;
                color: var(--primary);
                margin: 24px 0 12px 0;
            }

            .risk-matrix {
                background: rgba(255, 255, 255, 0.02);
                border: 1px solid rgba(255, 255, 255, 0.04);
                border-radius: 16px;
                padding: 16px;
                margin-bottom: 20px;
            }

            .risk-factor-list {
                list-style: none;
                display: flex;
                flex-direction: column;
                gap: 10px;
            }

            .risk-factor-item {
                display: flex;
                align-items: flex-start;
                gap: 10px;
                font-size: 14px;
                color: #e5e7eb;
                line-height: 1.4;
            }

            .risk-factor-item i {
                color: #fbbf24;
                margin-top: 3px;
                font-size: 12px;
            }

            .raw-reason-box {
                background: rgba(0, 0, 0, 0.2);
                border: 1px solid rgba(255, 255, 255, 0.05);
                border-radius: 12px;
                padding: 16px;
                font-size: 14px;
                color: var(--text-muted);
                line-height: 1.5;
                white-space: pre-wrap;
            }

            footer {
                text-align: center;
                padding: 40px;
                color: var(--text-muted);
                font-size: 13px;
                border-top: 1px solid rgba(255, 255, 255, 0.04);
                background: rgba(10, 14, 23, 0.2);
            }
        </style>
    </head>
    <body>
        <header>
            <div class="logo">
                <i class="fa-solid fa-shield-halved"></i>
                <span>Aura Guard</span>
            </div>
            <div class="system-status">
                <div class="status-indicator" id="statusIndicator"></div>
                <span id="statusText">Agent Engine Online</span>
            </div>
        </header>

        <div class="container">
            <!-- Alert Banner for errors/not configured runtime engine -->
            <div class="alert-banner" id="alertBanner">
                <i class="fa-solid fa-circle-exclamation"></i>
                <div class="alert-content">
                    <h3 id="alertTitle">Configuration Warning</h3>
                    <p id="alertMessage">The dashboard cannot communicate with Vertex AI. Make sure AGENT_RUNTIME_ID is correct.</p>
                </div>
            </div>

            <div class="dashboard-title-area">
                <div>
                    <h1>Expense Approvals</h1>
                    <p style="color: var(--text-muted); font-size: 14px; margin-top: 4px;">Pending manager sign-offs routed from autonomous agent audits</p>
                </div>
                <button class="btn-refresh" onclick="loadPendingApprovals()">
                    <i class="fa-solid fa-arrows-rotate"></i>
                    Refresh
                </button>
            </div>

            <!-- Dashboard Grid -->
            <div class="grid" id="dashboardGrid">
                <!-- Loading State -->
                <div class="empty-state" id="loadingState">
                    <i class="fa-solid fa-circle-notch fa-spin"></i>
                    <h3>Retrieving audit queue</h3>
                    <p>Loading pending reviews from Vertex AI agent session database...</p>
                </div>
            </div>
        </div>

        <!-- Slide Out Drawer for Compliance Review -->
        <div class="drawer-overlay" id="drawerOverlay" onclick="closeDrawer()"></div>
        <div class="drawer" id="drawer">
            <div>
                <div class="drawer-header">
                    <h2>
                        <i class="fa-solid fa-clipboard-check" style="color: var(--primary)"></i>
                        Compliance Audit
                    </h2>
                    <button class="btn-close-drawer" onclick="closeDrawer()">
                        <i class="fa-solid fa-xmark"></i>
                    </button>
                </div>

                <div class="drawer-scroll-body">
                    <div class="risk-matrix">
                        <div class="meta-item">
                            <span class="meta-label">Session ID</span>
                            <span class="meta-value" id="drawerSessionId" style="font-family: monospace; font-size: 12px;">-</span>
                        </div>
                        <div class="meta-item">
                            <span class="meta-label">Audited Value</span>
                            <span class="meta-value" id="drawerAmount" style="font-weight: 700; color: #ffffff;">-</span>
                        </div>
                        <div class="meta-item">
                            <span class="meta-label">Risk Assessment</span>
                            <span id="drawerRiskBadge" class="badge badge-low">LOW</span>
                        </div>
                    </div>

                    <div class="section-title">Verified Risk Factors</div>
                    <ul class="risk-factor-list" id="drawerRiskFactors">
                        <!-- Populated dynamically -->
                    </ul>

                    <div class="section-title">Agent Explanation</div>
                    <div class="raw-reason-box" id="drawerExplanation">
                        No detailed explanation recorded.
                    </div>

                    <div class="section-title">Raw Compliance Alert</div>
                    <div class="raw-reason-box" id="drawerRawMsg" style="font-size: 12px; font-family: monospace; max-height: 180px; overflow-y: auto;">
                        -
                    </div>
                </div>
            </div>

            <div class="btn-group" id="drawerActionGroup">
                <!-- Buttons dynamically loaded to target correct session ID -->
            </div>
        </div>

        <footer>
            &copy; 2026 Aura Guard Standalone Manager Dashboard Service • Powered by Google ADK & Vertex AI Agent Runtime
        </footer>

        <script>
            let pendingItems = [];

            async function loadPendingApprovals() {
                const grid = document.getElementById("dashboardGrid");
                const indicator = document.getElementById("statusIndicator");
                const statusText = document.getElementById("statusText");
                const banner = document.getElementById("alertBanner");
                
                grid.innerHTML = `
                    <div class="empty-state">
                        <i class="fa-solid fa-circle-notch fa-spin"></i>
                        <h3>Retrieving audit queue</h3>
                        <p>Loading pending reviews from Vertex AI agent session database...</p>
                    </div>
                `;
                banner.style.display = "none";

                try {
                    const response = await fetch("/api/pending");
                    const data = await response.json();
                    
                    if (data.status === "error") {
                        // Display error banner
                        banner.style.display = "flex";
                        document.getElementById("alertTitle").innerText = data.message;
                        document.getElementById("alertMessage").innerText = data.details || "Check system logs for more details.";
                        
                        indicator.className = "status-indicator error";
                        statusText.innerText = "Connection Failed";

                        grid.innerHTML = `
                            <div class="empty-state">
                                <i class="fa-solid fa-triangle-exclamation" style="color: var(--rose);"></i>
                                <h3>Failed to Fetch Queue</h3>
                                <p>${data.message}</p>
                            </div>
                        `;
                        return;
                    }

                    indicator.className = "status-indicator";
                    statusText.innerText = "Agent Engine Online";

                    pendingItems = data.pending || [];

                    if (pendingItems.length === 0) {
                        grid.innerHTML = `
                            <div class="empty-state">
                                <i class="fa-solid fa-circle-check" style="color: var(--emerald);"></i>
                                <h3>Clear Queue</h3>
                                <p>All routed expenses have been reviewed. No approvals are currently pending.</p>
                            </div>
                        `;
                        return;
                    }

                    grid.innerHTML = "";
                    pendingItems.forEach(item => {
                        grid.appendChild(createExpenseCard(item));
                    });

                } catch (error) {
                    console.error("Error loading approvals:", error);
                    banner.style.display = "flex";
                    document.getElementById("alertTitle").innerText = "Network Error";
                    document.getElementById("alertMessage").innerText = "Failed to connect to dashboard API. Ensure the FastAPI service is running.";
                    
                    indicator.className = "status-indicator error";
                    statusText.innerText = "Offline";

                    grid.innerHTML = `
                        <div class="empty-state">
                            <i class="fa-solid fa-wifi-slash" style="color: var(--rose);"></i>
                            <h3>Offline</h3>
                            <p>Cannot reach the manager dashboard service API.</p>
                        </div>
                    `;
                }
            }

            function createExpenseCard(item) {
                const card = document.createElement("div");
                card.className = "card";
                if (item.is_security_event) {
                    card.classList.add("security-alert");
                }

                // Determine risk badge class
                let badgeClass = "badge-low";
                const rating = (item.risk_rating || "").toLowerCase();
                if (rating.includes("high")) badgeClass = "badge-high";
                else if (rating.includes("med") || rating.includes("warn")) badgeClass = "badge-medium";

                // Format amount
                const amt = typeof item.amount === 'number' ? item.amount.toFixed(2) : parseFloat(item.amount || 0).toFixed(2);

                card.innerHTML = `
                    <div>
                        <div class="card-header">
                            <span class="amount">$${amt}</span>
                            <div>
                                ${item.is_security_event ? '<span class="badge badge-security"><i class="fa-solid fa-triangle-exclamation"></i> Security</span>' : ''}
                                <span class="badge ${badgeClass}">${item.risk_rating}</span>
                            </div>
                        </div>
                        <div class="card-body">
                            <div class="meta-item">
                                <span class="meta-label">Submitter</span>
                                <span class="meta-value">${item.submitter}</span>
                            </div>
                            <div class="meta-item">
                                <span class="meta-label">Category</span>
                                <span class="meta-value">${item.category}</span>
                            </div>
                            <div class="meta-item">
                                <span class="meta-label">Date</span>
                                <span class="meta-value">${item.date}</span>
                            </div>
                            <div class="card-description">
                                ${item.description}
                            </div>
                        </div>
                    </div>
                    <div>
                        <button class="btn btn-details" onclick="openDrawer('${item.session_id}')">
                            <i class="fa-solid fa-magnifying-glass-chart"></i>
                            View Compliance Review
                        </button>
                        <div class="btn-group">
                            <button class="btn btn-approve" id="approve-btn-${item.session_id}" onclick="performAction('${item.session_id}', '${item.interrupt_id}', true)">
                                <div class="spinner"></div>
                                <span>Approve</span>
                            </button>
                            <button class="btn btn-reject" id="reject-btn-${item.session_id}" onclick="performAction('${item.session_id}', '${item.interrupt_id}', false)">
                                <div class="spinner"></div>
                                <span>Reject</span>
                            </button>
                        </div>
                    </div>
                `;
                return card;
            }

            function openDrawer(sessionId) {
                const item = pendingItems.find(i => i.session_id === sessionId);
                if (!item) return;

                document.getElementById("drawerSessionId").innerText = item.session_id;
                document.getElementById("drawerAmount").innerText = `$${item.amount.toFixed(2)}`;

                // Set risk badge
                const badge = document.getElementById("drawerRiskBadge");
                badge.innerText = item.risk_rating;
                badge.className = "badge";
                const rating = (item.risk_rating || "").toLowerCase();
                if (rating.includes("high")) badge.classList.add("badge-high");
                else if (rating.includes("med")) badge.classList.add("badge-medium");
                else badge.classList.add("badge-low");

                // Risk Factors list
                const factorList = document.getElementById("drawerRiskFactors");
                factorList.innerHTML = "";
                if (item.risk_factors && item.risk_factors.length > 0) {
                    item.risk_factors.forEach(factor => {
                        const li = document.createElement("li");
                        li.className = "risk-factor-item";
                        li.innerHTML = `<i class="fa-solid fa-circle-exclamation"></i><span>${factor}</span>`;
                        factorList.appendChild(li);
                    });
                } else {
                    factorList.innerHTML = `<li class="risk-factor-item"><i class="fa-solid fa-circle-check" style="color: var(--emerald);"></i><span>No critical risk factors flagged</span></li>`;
                }

                // Explanation & Raw
                document.getElementById("drawerExplanation").innerText = item.explanation || "No detailed explanation recorded by auditor agent.";
                document.getElementById("drawerRawMsg").innerText = item.raw_message || "";

                // Update action buttons in drawer
                const actionGroup = document.getElementById("drawerActionGroup");
                actionGroup.innerHTML = `
                    <button class="btn btn-approve" id="drawer-approve-btn-${item.session_id}" onclick="performAction('${item.session_id}', '${item.interrupt_id}', true)">
                        <div class="spinner"></div>
                        <span>Approve Expense</span>
                    </button>
                    <button class="btn btn-reject" id="drawer-reject-btn-${item.session_id}" onclick="performAction('${item.session_id}', '${item.interrupt_id}', false)">
                        <div class="spinner"></div>
                        <span>Reject Expense</span>
                    </button>
                `;

                // Slide open
                document.getElementById("drawer").classList.add("open");
                document.getElementById("drawerOverlay").classList.add("open");
            }

            function closeDrawer() {
                document.getElementById("drawer").classList.remove("open");
                document.getElementById("drawerOverlay").classList.remove("open");
            }

            async function performAction(sessionId, interruptId, isApprove) {
                // Set loading status
                const btnId = isApprove ? `approve-btn-${sessionId}` : `reject-btn-${sessionId}`;
                const drawerBtnId = isApprove ? `drawer-approve-btn-${sessionId}` : `drawer-reject-btn-${sessionId}`;
                
                const btn = document.getElementById(btnId);
                const drawerBtn = document.getElementById(drawerBtnId);

                if (btn) btn.classList.add("loading");
                if (drawerBtn) drawerBtn.classList.add("loading");

                try {
                    const response = await fetch(`/api/action/${sessionId}`, {
                        method: "POST",
                        headers: {
                            "Content-Type": "application/json"
                        },
                        body: JSON.stringify({
                            approved: isApprove,
                            interrupt_id: interruptId
                        })
                    });

                    if (!response.ok) {
                        const errorDetails = await response.json();
                        throw new Error(errorDetails.detail || "Action processing failed");
                    }

                    const result = await response.json();
                    
                    // Show success notification and reload
                    alert(`Expense ${isApprove ? 'APPROVED' : 'REJECTED'} successfully!`);
                    
                    closeDrawer();
                    loadPendingApprovals();

                } catch (error) {
                    console.error("Action error:", error);
                    alert(`Action failed: ${error.message}`);
                } finally {
                    if (btn) btn.classList.remove("loading");
                    if (drawerBtn) drawerBtn.classList.remove("loading");
                }
            }

            // Initial load
            window.onload = loadPendingApprovals;
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)

if __name__ == "__main__":
    import uvicorn
    # Default port 8081 to avoid conflict with the default 8080 port for ambient service
    port = int(os.environ.get("PORT", 8081))
    uvicorn.run(app, host="0.0.0.0", port=port)
