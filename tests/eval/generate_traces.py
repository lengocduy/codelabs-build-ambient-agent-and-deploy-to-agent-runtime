#!/usr/bin/env python3
import os
import json
import base64
from pathlib import Path

from google.adk.agents.run_config import RunConfig, StreamingMode
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from expense_agent.agent import root_agent

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
    text_lower = text.lower()
    return any(kw in text_lower for kw in PROMPT_INJECTION_KEYWORDS)

def clean_content(content):
    if not content:
        return None
    cleaned_parts = []
    for part in content.parts:
        part_dict = {}
        if part.text is not None:
            part_dict["text"] = part.text
        if part.function_call is not None:
            call = part.function_call
            part_dict["function_call"] = {
                "name": call.name,
                "args": call.args
            }
        if part.function_response is not None:
            resp = part.function_response
            part_dict["function_response"] = {
                "name": resp.name or resp.id or "human_approval",
                "response": resp.response
            }
        if part_dict:
            cleaned_parts.append(part_dict)
    
    return {
        "role": content.role,
        "parts": cleaned_parts
    }

def main():
    dataset_path = Path("tests/eval/datasets/basic-dataset.json")
    output_dir = Path("artifacts/traces")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "generated_traces.json"

    print(f"Loading dataset from {dataset_path}...")
    with open(dataset_path, "r") as f:
        dataset = json.load(f)

    generated_cases = []

    for case in dataset.get("eval_cases", []):
        case_id = case["eval_case_id"]
        print(f"\n--- Running case: {case_id} ---")

        # Load case prompt
        prompt_data = case["prompt"]
        prompt_text = prompt_data["parts"][0]["text"]
        payload = json.loads(prompt_text)
        description = payload["data"].get("description", "")

        # Initialize runner & session
        session_service = InMemorySessionService()
        session = session_service.create_session_sync(user_id="eval_user", app_name="expense_agent")
        runner = Runner(agent=root_agent, session_service=session_service, app_name="expense_agent")

        # Run first turn
        user_message = types.Content(
            role="user",
            parts=[types.Part.from_text(text=prompt_text)]
        )
        print("Executing first turn...")
        events = list(runner.run(
            new_message=user_message,
            user_id="eval_user",
            session_id=session.id,
            run_config=RunConfig(streaming_mode=StreamingMode.SSE)
        ))

        # Check if paused for human approval
        is_paused = False
        for e in events:
            if e.long_running_tool_ids and "human_approval" in e.long_running_tool_ids:
                is_paused = True
                break

        if is_paused:
            print("Interrupt detected. Automating decision...")
            is_injection = detect_prompt_injection(description)
            decision = "reject" if is_injection else "approve"
            print(f"Decision: {decision}")

            # Send function response to resume
            resume_message = types.Content(
                role="user",
                parts=[
                    types.Part(
                        function_response=types.FunctionResponse(
                            id="human_approval",
                            response={"human_approval": decision}
                        )
                    )
                ]
            )
            list(runner.run(
                new_message=resume_message,
                user_id="eval_user",
                session_id=session.id,
                run_config=RunConfig(streaming_mode=StreamingMode.SSE)
            ))

        # Retrieve final events from session
        updated_session = session_service.get_session_sync(
            user_id="eval_user",
            app_name="expense_agent",
            session_id=session.id
        )

        # Map session events to turns
        turns = []
        current_events = []
        for event in updated_session.events:
            if not event.content:
                continue
            
            # Start new turn on subsequent user message
            if event.author == "user" and current_events:
                turns.append({
                    "turn_index": len(turns),
                    "events": current_events
                })
                current_events = []

            # Map author
            if event.author == "user":
                is_func_resp = any(p.function_response is not None for p in event.content.parts)
                author = "tool" if is_func_resp else "user"
            else:
                author = "expense_agent"

            current_events.append({
                "author": author,
                "content": clean_content(event.content)
            })

        if current_events:
            turns.append({
                "turn_index": len(turns),
                "events": current_events
            })

        # Extract final agent response text
        final_text = ""
        for turn in reversed(turns):
            for event in reversed(turn["events"]):
                if event["author"] == "expense_agent":
                    parts = event["content"].get("parts", [])
                    for part in parts:
                        if "text" in part and part["text"].strip():
                            final_text = part["text"]
                            break
                if final_text:
                    break
            if final_text:
                break

        print(f"Final Response text extracted: {final_text}")

        # Construct trace case
        generated_case = {
            "eval_case_id": case_id,
            "prompt": prompt_data,
            "responses": [
                {
                    "response": {
                        "role": "model",
                        "parts": [
                            {
                                "text": final_text
                            }
                        ]
                    }
                }
            ],
            "agent_data": {
                "agents": {
                    "expense_agent": {
                        "agent_id": "expense_agent",
                        "instruction": "Expense auditor agent"
                    }
                },
                "turns": turns
            }
        }
        generated_cases.append(generated_case)

    # Save to generated_traces.json
    output_payload = {
        "eval_cases": generated_cases
    }
    with open(output_path, "w") as f:
        json.dump(output_payload, f, indent=2)

    print(f"\nSaved {len(generated_cases)} traces to {output_path}")

if __name__ == "__main__":
    main()
