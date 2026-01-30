# Use the official Python image from the Docker Hub
FROM python:3.9-slim

# Set the working directory
WORKDIR /app

# Copy the requirements file
COPY pyproject.toml .

# Install uv for dependency management
RUN apt-get update && apt-get install -y curl && \
    curl -sSL https://raw.githubusercontent.com/uv/uv/master/get-uv.py | python3 - && \
    uv install

# Copy the rest of the application code
COPY . .

# Command to run the application
CMD ["python", "src/cli.py"]