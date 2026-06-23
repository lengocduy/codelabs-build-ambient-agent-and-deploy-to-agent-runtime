# ruff: noqa
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

import datetime
from zoneinfo import ZoneInfo
import os
import base64
import json
from typing import Any, AsyncGenerator
from pydantic import BaseModel
from dotenv import load_dotenv

# Load env variables from .env if present
load_dotenv()

from google.adk.agents import LlmAgent
from google.adk.apps import App
from google.adk.models import Gemini
from google.adk.workflow import Workflow, node
from google.adk.events.event import Event
from google.adk.events.request_input import RequestInput
from google.adk.agents.context import Context
from google.genai import types

from .config import EXPENSE_THRESHOLD, LLM_MODEL

# Setup Google Cloud/Vertex AI settings conditionally
use_vertex = os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", "False").lower() in ("true", "1", "yes")

if use_vertex:
    import google.auth
    try:
        _, project_id = google.auth.default()
        os.environ.setdefault("GOOGLE_CLOUD_PROJECT", project_id)
    except Exception:
        pass
    os.environ["GOOGLE_CLOUD_LOCATION"] = "global"


# Pydantic Schemas for validation
class ExpenseReport(BaseModel):
    amount: float
    submitter: str
    category: str
    description: str
    date: str


class RiskReview(BaseModel):
    risk_rating: str  # low, medium, high
    risk_factors: list[str]
    explanation: str


def extract_expense_data(node_input: Any) -> ExpenseReport:
    """Helper to extract and decode expense report details from JSON/PubSub payload."""
    data_val = None

    # 1. Resolve raw string/dict from node_input (which might be types.Content)
    if isinstance(node_input, types.Content):
        text = ""
        if node_input.parts:
            text = "".join(part.text for part in node_input.parts if part.text)
        try:
            node_input = json.loads(text)
        except Exception:
            raise ValueError(f"Input text must be a valid JSON: {text}")

    if isinstance(node_input, str):
        try:
            node_input = json.loads(node_input)
        except Exception:
            raise ValueError(f"Input string must be a valid JSON: {node_input}")

    if not isinstance(node_input, dict):
        raise ValueError(f"Expected dict or JSON string, got {type(node_input)}")

    # 2. Check if wrapped in Pub/Sub message structure
    if "message" in node_input and isinstance(node_input["message"], dict):
        data_val = node_input["message"].get("data")
    else:
        data_val = node_input.get("data")

    if data_val is None:
        # Fallback: check if the input dictionary is the expense report itself
        if "amount" in node_input:
            data_val = node_input
        else:
            raise ValueError("Missing 'data' key or 'amount' in JSON input")

    # 3. Decode base64 if it's a base64-encoded string
    if isinstance(data_val, str):
        try:
            decoded = base64.b64decode(data_val).decode('utf-8')
            data_dict = json.loads(decoded)
        except Exception:
            try:
                data_dict = json.loads(data_val)
            except Exception:
                raise ValueError(f"Could not parse data string: {data_val}")
    elif isinstance(data_val, dict):
        data_dict = data_val
    else:
        raise ValueError(f"Invalid data type under 'data' key: {type(data_val)}")

    # 4. Construct and validate
    return ExpenseReport(
        amount=float(data_dict.get("amount", 0.0)),
        submitter=data_dict.get("submitter", "Unknown"),
        category=data_dict.get("category", "Uncategorized"),
        description=data_dict.get("description", "No description"),
        date=data_dict.get("date", "Unknown"),
    )


@node
def parse_event(ctx: Context, node_input: Any) -> Event:
    """Parses incoming event payload, stores details in state, and routes based on threshold."""
    expense = extract_expense_data(node_input)
    expense_dict = expense.model_dump()
    
    route = "approve" if expense.amount < EXPENSE_THRESHOLD else "review"
    
    return Event(
        output=expense_dict,
        route=route,
        state={"expense": expense_dict}
    )


@node
async def auto_approve(node_input: dict) -> AsyncGenerator[Event, None]:
    """Plain function node executing instant auto-approval for expenses under the threshold."""
    expense = ExpenseReport(**node_input)
    result = {
        "status": "approved",
        "amount": expense.amount,
        "submitter": expense.submitter,
        "category": expense.category,
        "description": expense.description,
        "date": expense.date,
        "risk_rating": "low",
        "risk_factors": [],
        "explanation": "Auto-approved instantly (amount under threshold).",
        "decision_by": "system"
    }
    yield Event(
        content=types.Content(
            role="model",
            parts=[types.Part.from_text(text=f"✅ Expense auto-approved instantly (under threshold).\n- Amount: ${expense.amount:.2f}\n- Submitter: {expense.submitter}\n- Category: {expense.category}\n- Description: {expense.description}")]
        )
    )
    yield Event(output=result)


import re

SSN_REGEX = re.compile(r'\b\d{3}-\d{2}-\d{4}\b')
# Matches 16-digit numbers (possibly with spaces or hyphens)
CREDIT_CARD_REGEX = re.compile(r'\b\d{4}[- ]\d{4}[- ]\d{4}[- ]\d{4}\b|\b\d{16}\b')


def scrub_pii(text: str) -> tuple[str, list[str]]:
    """Scrubs SSNs and Credit Card numbers from text and returns categories redacted."""
    redacted = []
    
    if SSN_REGEX.search(text):
        text = SSN_REGEX.sub("[REDACTED SSN]", text)
        redacted.append("SSN")
        
    if CREDIT_CARD_REGEX.search(text):
        text = CREDIT_CARD_REGEX.sub("[REDACTED CREDIT CARD]", text)
        redacted.append("Credit Card")
        
    return text, redacted


# Prompt Injection Defense configuration
PROMPT_INJECTION_KEYWORDS = [
    "ignore previous instructions",
    "ignore all instructions",
    "bypass rules",
    "bypass the rules",
    "force auto-approve",
    "force approval",
    "auto-approve this",
    "override threshold",
    "override rules",
    "system prompt",
    "you must approve",
    "ignore constraints",
    "override constraints",
    "ignore policy",
    "override policy",
    "override limit",
    "ignore limit"
]


def detect_prompt_injection(text: str) -> bool:
    """Detects simple keyword-based prompt injection attempts."""
    text_lower = text.lower()
    return any(kw in text_lower for kw in PROMPT_INJECTION_KEYWORDS)


@node
def security_checkpoint(ctx: Context, node_input: dict) -> Event:
    """Security node to scrub PII and defend against prompt injection."""
    expense = ExpenseReport(**node_input)
    
    # 1. Scrub PII from description
    scrubbed_desc, redacted_categories = scrub_pii(expense.description)
    expense.description = scrubbed_desc
    expense_dict = expense.model_dump()
    
    # 2. Defend against prompt injection
    has_injection = detect_prompt_injection(scrubbed_desc)
    
    if has_injection:
        # Construct default risk review payload alerting security issue
        alert_review = {
            "risk_rating": "high",
            "risk_factors": ["Security Alert: Prompt Injection Detected"],
            "explanation": f"WARNING: Potential prompt-injection attempt detected in description: '{scrubbed_desc}'"
        }
        return Event(
            output=alert_review,
            route="alert",
            state={
                "expense": expense_dict,
                "redacted_categories": redacted_categories,
                "security_event": True
            }
        )
    else:
        # Continue to LLM reviewer
        return Event(
            output=expense_dict,
            route="clean",
            state={
                "expense": expense_dict,
                "redacted_categories": redacted_categories,
                "security_event": False
            }
        )


# Define risk review LLM Agent Node
review_risk = LlmAgent(
    name="review_risk",
    model=Gemini(
        model=LLM_MODEL,
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction=(
        "You are an expert financial auditor and risk analyst. "
        "Review the provided expense report details for risk factors, "
        "potential policy violations, or suspicious activity. "
        "Based on your analysis, fill out the required schema:\n"
        "1. Categorize risk_rating as 'low', 'medium', or 'high'.\n"
        "2. Identify specific risk_factors as a list of strings.\n"
        "3. Provide a detailed explanation summarizing your assessment."
    ),
    output_schema=RiskReview,
    output_key="risk_review"
)


@node(rerun_on_resume=True)
async def human_review(ctx: Context, node_input: RiskReview) -> AsyncGenerator[Event, None]:
    """Pauses the workflow using RequestInput to ask for human approval, then records outcome."""
    expense_dict = ctx.state.get("expense")
    if not expense_dict:
        raise ValueError("Expense report data not found in state.")
    
    expense = ExpenseReport(**expense_dict)
    
    # Check if the human has responded yet
    if not ctx.resume_inputs or "human_approval" not in ctx.resume_inputs:
        is_security_event = ctx.state.get("security_event", False)
        alert_header = "🚨 SECURITY ALERT" if is_security_event else "⚠️ ALERT"
        
        redacted = ctx.state.get("redacted_categories", [])
        redacted_msg = f" (Redacted PII: {', '.join(redacted)})" if redacted else ""
        
        msg = (
            f"{alert_header}: Expense of ${expense.amount:.2f} requires human approval!\n"
            f"- Submitter: {expense.submitter}\n"
            f"- Category: {expense.category}\n"
            f"- Description: {expense.description}{redacted_msg}\n"
            f"- Date: {expense.date}\n\n"
            f"Risk Analysis:\n"
            f"- Risk Rating: {node_input.risk_rating.upper()}\n"
            f"- Risk Factors: {', '.join(node_input.risk_factors) if node_input.risk_factors else 'None'}\n"
            f"- Explanation: {node_input.explanation}\n\n"
            f"Do you approve or reject this expense report? (Type 'approve' or 'reject')"
        )
        yield RequestInput(
            interrupt_id="human_approval",
            message=msg
        )
        return

    # Process response
    decision_val = ctx.resume_inputs["human_approval"]
    if isinstance(decision_val, dict):
        decision_text = decision_val.get("response") or decision_val.get("human_approval") or next(iter(decision_val.values()))
    else:
        decision_text = decision_val
    decision_text = str(decision_text).strip().lower()
    is_approved = decision_text in ("approve", "approved", "yes", "y")
    status = "approved" if is_approved else "rejected"
    
    result = {
        "status": status,
        "amount": expense.amount,
        "submitter": expense.submitter,
        "category": expense.category,
        "description": expense.description,
        "date": expense.date,
        "risk_rating": node_input.risk_rating,
        "risk_factors": node_input.risk_factors,
        "explanation": node_input.explanation,
        "decision_by": "human"
    }
    
    ui_text = f"Expense {status} by human. Submitter: {expense.submitter}, Amount: ${expense.amount:.2f}"
    yield Event(
        content=types.Content(
            role="model",
            parts=[types.Part.from_text(text=ui_text)]
        )
    )
    yield Event(
        output=result,
        state={"status": status}
    )


# Root Workflow graph wiring
root_agent = Workflow(
    name="root_agent",
    edges=[
        ('START', parse_event),
        (parse_event, {"approve": auto_approve, "review": security_checkpoint}),
        (security_checkpoint, {"clean": review_risk, "alert": human_review}),
        (review_risk, human_review),
    ]
)

app = App(
    root_agent=root_agent,
    name="expense_agent",
)
