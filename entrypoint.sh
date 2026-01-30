#!/bin/bash
set -e

REPO_PATH="/app/workspace/repo"

# Clone repository if not exists
if [ ! -d "$REPO_PATH/.git" ]; then
    echo "Cloning repository ${GITHUB_REPOSITORY}..."
    git clone "https://x-access-token:${GITHUB_TOKEN}@github.com/${GITHUB_REPOSITORY}.git" "$REPO_PATH"
    echo "Repository cloned to $REPO_PATH"
else
    echo "Repository exists at $REPO_PATH, fetching latest..."
    cd "$REPO_PATH"
    git fetch origin
    git reset --hard origin/$(git remote show origin | grep 'HEAD branch' | cut -d' ' -f5)
    echo "Repository updated"
fi

# Execute the command
exec "$@"
