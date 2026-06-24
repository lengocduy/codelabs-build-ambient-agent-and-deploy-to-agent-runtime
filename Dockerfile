# Use python base image
FROM python:3.11-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PORT=8080

# Install uv for fast dependency management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Set working directory
WORKDIR /app

# Copy dependency configuration files
COPY pyproject.toml uv.lock ./
COPY submission_frontend/pyproject.toml ./submission_frontend/

# Synchronize dependencies
RUN uv pip install --system -r pyproject.toml -r submission_frontend/pyproject.toml

# Copy code
COPY expense_agent/ ./expense_agent/
COPY submission_frontend/ ./submission_frontend/

# Expose port
EXPOSE 8080

# Command to run the dashboard
CMD ["python", "submission_frontend/main.py"]
