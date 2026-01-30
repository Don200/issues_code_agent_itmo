# Use the official Python image from the Docker Hub
FROM python:3.9-slim

# Set the working directory
WORKDIR /app

# Copy the requirements file
COPY pyproject.toml .

# Install uv instead of pip
RUN apt-get update && \
    apt-get install -y curl && \
    curl -sSL https://get.uv.dev/uv.sh | sh

# Install dependencies using uv
RUN uv install

# Copy the rest of the application code
COPY . .

# Command to run the application
CMD ["python", "src/cli.py"]