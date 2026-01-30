FROM python:3.11-slim

WORKDIR /app

# Install git (needed for GitPython)
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency files
COPY pyproject.toml ./

# Install dependencies
RUN pip install --no-cache-dir -e ".[dev]"

# Copy source code
COPY src/ ./src/
COPY tests/ ./tests/

# Copy entrypoint script
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Set environment variables
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

# Create workspace directory
RUN mkdir -p /app/workspace /app/logs

# Configure git for commits
RUN git config --global --add safe.directory '*' && \
    git config --global user.email "agent@sdlc.local" && \
    git config --global user.name "SDLC Agent"

ENTRYPOINT ["/entrypoint.sh", "sdlc-agent"]
CMD ["--help"]
