.PHONY: install playground test clean

# Install project dependencies using uv
install:
	uv sync
	uv tool install google-agents-cli --force

# Launch the interactive local agent playground UI on default port 8080. Customize if conflicts with other apps
playground:
	agents-cli playground --port=8080

# Run unit and integration tests
test:
	uv run pytest tests/unit tests/integration

# Clean up build artifacts and caches
clean:
	rm -rf .pytest_cache .venv
