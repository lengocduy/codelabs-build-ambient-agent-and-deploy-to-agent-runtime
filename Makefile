.PHONY: help install playground run test generate-traces grade fe-local fe-staging fe-production run-all-local clean

# Default goal shows help
help:
	@echo "Available commands in this Makefile:"
	@echo "  make install         - Install project dependencies using uv"
	@echo "  make playground      - Launch the interactive local agent playground UI on port 8080"
	@echo "  make run             - Run the ambient web service locally on port 8080"
	@echo "  make run-all-local   - Run both local agent (port 8080) and dashboard (port 8081) concurrently in SQLite mode"
	@echo "  make fe-local        - Run the manager dashboard locally using .env.local (SQLite offline mode)"
	@echo "  make fe-staging      - Run the manager dashboard locally pointing to the staging reasoning engine"
	@echo "  make fe-production   - Run the manager dashboard locally pointing to the production reasoning engine"
	@echo "  make test            - Run unit and integration tests"
	@echo "  make generate-traces - Generate traces for evaluation"
	@echo "  make grade           - Grade the generated traces"
	@echo "  make clean           - Clean up build artifacts and caches"

# Install project dependencies using uv
install:
	uv sync
	uv tool install google-agents-cli --force

# Launch the interactive local agent playground UI on default port 8080. Customize if conflicts with other apps
playground:
	agents-cli playground --port=8080

# Run the ambient web service locally on default port 8080. Customize if conflicts with other apps
run:
	PORT=8080 uv run python -m expense_agent.fast_api_app

# Run unit and integration tests
test:
	uv run pytest tests/unit tests/integration

# Generate traces for evaluation
generate-traces:
	uv run python tests/eval/generate_traces.py

# Grade the generated traces
grade:
	agents-cli eval grade --traces artifacts/traces/generated_traces.json --config tests/eval/eval_config.yaml

# Run the manager dashboard locally using .env.local configuration (SQLite offline mode)
fe-local:
	ENV_FILE=.env.local PORT=8081 uv run python submission_frontend/main.py

# Run the manager dashboard locally pointing to the staging reasoning engine
fe-staging:
	ENV_FILE=.env.staging PORT=8081 uv run python submission_frontend/main.py

# Run the manager dashboard locally pointing to the production reasoning engine
fe-production:
	ENV_FILE=.env.production PORT=8081 uv run python submission_frontend/main.py

# Run both local agent (port 8080) and dashboard (port 8081) concurrently in SQLite mode
run-all-local:
	@echo "Starting local agent backend and dashboard services... Press Ctrl+C to stop both."
	@trap 'kill 0' EXIT; \
	SESSION_SERVICE_URI="sqlite:///shared_sessions.db" PORT=8080 uv run python -m expense_agent.fast_api_app & \
	ENV_FILE=.env.local PORT=8081 uv run python submission_frontend/main.py

# Clean up build artifacts and caches
clean:
	rm -rf .pytest_cache .venv


