import os
import json
import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient

from submission_frontend.main import app

client = TestClient(app)

@patch.dict(os.environ, {"AGENT_RUNTIME_ID": "projects/test-proj/locations/us-east1/reasoningEngines/123456"})
@patch("submission_frontend.main.VertexAiSessionService")
def test_dashboard_get_index(mock_service_class):
    """Test that the manager dashboard index page loads correctly."""
    response = client.get("/")
    assert response.status_code == 200
    assert "Expense Manager Dashboard" in response.text
    assert "Aura Guard" in response.text

@patch.dict(os.environ, {"AGENT_RUNTIME_ID": "projects/test-proj/locations/us-east1/reasoningEngines/123456"})
@patch("submission_frontend.main.VertexAiSessionService")
@pytest.mark.asyncio
async def test_api_pending_no_sessions(mock_service_class):
    """Test GET /api/pending returning success when no sessions are found."""
    mock_service_instance = AsyncMock()
    mock_service_class.return_value = mock_service_instance
    
    # Mock list_sessions to return empty sessions
    mock_list_sessions_res = AsyncMock()
    mock_list_sessions_res.sessions = []
    mock_service_instance.list_sessions.return_value = mock_list_sessions_res
    
    response = client.get("/api/pending")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["pending"] == []

@patch.dict(os.environ, {"AGENT_RUNTIME_ID": "projects/test-proj/locations/us-east1/reasoningEngines/123456"})
@patch("submission_frontend.main.VertexAiSessionService")
@pytest.mark.asyncio
async def test_api_pending_with_unresolved_session(mock_service_class):
    """Test GET /api/pending returning unresolved session approvals."""
    mock_service_instance = AsyncMock()
    mock_service_class.return_value = mock_service_instance
    
    # Mock session
    mock_session = AsyncMock()
    mock_session.id = "test-session-1"
    mock_session.user_id = "test-user-1"
    
    mock_list_sessions_res = AsyncMock()
    mock_list_sessions_res.sessions = [mock_session]
    mock_service_instance.list_sessions.return_value = mock_list_sessions_res
    
    # Mock event history
    from unittest.mock import MagicMock
    mock_event1 = MagicMock()
    mock_event1.author = "user"
    mock_event1.content = MagicMock()
    
    mock_part1 = MagicMock()
    mock_part1.text = json.dumps({
        "data": {
            "amount": 150.0,
            "submitter": "Bob",
            "category": "Travel",
            "description": "Hotel stay",
            "date": "2026-06-22"
        }
    })
    mock_event1.content.parts = [mock_part1]
    mock_event1.get_function_calls.return_value = []
    mock_event1.get_function_responses.return_value = []
    
    mock_event2 = MagicMock()
    mock_event2.author = "expense_agent"
    
    mock_call = MagicMock()
    mock_call.id = "call_xyz123"
    mock_call.name = "adk_request_input"
    mock_call.args = {
        "message": "⚠️ ALERT: Expense of $150.00 requires human approval!\nRisk Rating: LOW\nRisk Factors: None\nExplanation: Standard travel cost."
    }
    
    mock_event2.get_function_calls.return_value = [mock_call]
    mock_event2.get_function_responses.return_value = []
    
    # Mock get_session response
    mock_full_session = MagicMock()
    mock_full_session.id = "test-session-1"
    mock_full_session.user_id = "test-user-1"
    mock_full_session.events = [mock_event1, mock_event2]
    
    mock_service_instance.get_session.return_value = mock_full_session
    
    response = client.get("/api/pending")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert len(data["pending"]) == 1
    
    pending = data["pending"][0]
    assert pending["session_id"] == "test-session-1"
    assert pending["interrupt_id"] == "call_xyz123"
    assert pending["submitter"] == "Bob"
    assert pending["amount"] == 150.0
    assert pending["category"] == "Travel"
    assert pending["risk_rating"] == "LOW"
    assert "Standard travel cost." in pending["explanation"]


@patch.dict(os.environ, {"AGENT_RUNTIME_ID": "projects/test-proj/locations/us-east1/reasoningEngines/123456"})
@patch("submission_frontend.main.Runner")
@patch("submission_frontend.main.VertexAiSessionService")
def test_api_action_resume(mock_service_class, mock_runner_class):
    """Test POST /api/action/{session_id} resumes the session successfully."""
    from unittest.mock import MagicMock
    mock_service_instance = AsyncMock()
    mock_service_class.return_value = mock_service_instance

    mock_runner_instance = MagicMock()
    mock_runner_class.return_value = mock_runner_instance

    # Mock runner events generator
    mock_event = MagicMock()
    mock_event.output = {"status": "approved"}
    mock_event.content = MagicMock()
    mock_part = MagicMock()
    mock_part.text = "Expense approved by human."
    mock_event.content.parts = [mock_part]

    mock_runner_instance.run.return_value = [mock_event]

    payload = {
        "approved": True,
        "interrupt_id": "call_xyz123"
    }

    response = client.post("/api/action/test-session-1", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["final_output"] == {"status": "approved"}
    assert "Expense approved by human." in data["outputs"]

    # Verify Runner was initialized and run with correct parameters
    from unittest.mock import ANY
    from google.genai import types
    mock_runner_class.assert_called_once()
    
    expected_message = types.Content(
        role="user",
        parts=[
            types.Part(
                function_response=types.FunctionResponse(
                    id="call_xyz123",
                    name="adk_request_input",
                    response={
                        "approved": True,
                        "human_approval": "approve"
                    }
                )
            )
        ]
    )
    
    mock_runner_instance.run.assert_called_once_with(
        user_id="default-user",
        session_id="test-session-1",
        new_message=expected_message,
        run_config=ANY
    )

