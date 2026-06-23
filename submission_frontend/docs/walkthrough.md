# Walkthrough: Manager Dashboard Service Implementation

We have successfully created a standalone, fully-functional manager dashboard service in a new directory named `submission_frontend/`.

## Created Files

### 1. [submission_frontend/pyproject.toml](file:///Volumes/Investor/Learning/Google%205-Day%20AI%20Agents%20Intensive Course/ambient-expense-agent/submission_frontend/pyproject.toml)
Defines project metadata and specifies required python package dependencies:
- `fastapi`
- `uvicorn`
- `google-adk[gcp]`
- `google-cloud-aiplatform`

### 2. [submission_frontend/main.py](file:///Volumes/Investor/Learning/Google%205-Day%20AI%20Agents%20Intensive Course/ambient-expense-agent/submission_frontend/main.py)
Implements the FastAPI service with:
- **GET `/`**: Returns a premium dark-themed manager dashboard withOutfit Google Font, radial flows, custom-scrollbar, and backdrop-blur glassmorphism.
- **GET `/api/pending`**: Resolves active sessions from the ADK `VertexAiSessionService`, fetches history, and filters unresolved `adk_request_input` manual inputs.
- **POST `/api/action/{session_id}`**: Resumes paused sessions using the dictionary payload as the message argument and setting the user to `"default-user"`.

### 3. [tests/unit/test_manager_dashboard.py](file:///Volumes/Investor/Learning/Google%205-Day%20AI%20Agents%20Intensive Course/ambient-expense-agent/tests/unit/test_manager_dashboard.py)
Implements full unit test coverage using FastAPI's `TestClient` to verify the page loading, parsing of session events, and correct construction of the resumption message format.

## Verification & Testing

All unit and integration tests compiled and passed:
```bash
$ uv run pytest tests/unit tests/integration
======================= 14 passed, 19 warnings in 16.12s =======================
```
The manager dashboard unit tests verified:
- Index loading status.
- Session listing and correct parsing of risk analyses from the `adk_request_input` message.
- Correct resumption message structure:
  ```python
  {
      "role": "user",
      "parts": [
          {
              "function_response": {
                  "id": "call_xyz123",
                  "name": "adk_request_input",
                  "response": {
                      "approved": True,
                      "human_approval": "approve"
                  }
              }
          }
      ]
  }
  ```
