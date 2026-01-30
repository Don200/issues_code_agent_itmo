"""Tools for the SDLC Agent - enables LLM to interact with codebase and GitHub."""

import subprocess
from pathlib import Path
from typing import Any

import structlog
from langchain_core.tools import tool, StructuredTool
from pydantic import BaseModel, Field

from src.core.config import Settings
from src.github.client import GitHubClient

logger = structlog.get_logger()


class ToolContext:
    """Context holding dependencies for tools."""

    # Fixed workspace path - repo is cloned by entrypoint.sh
    REPO_PATH = Path("/app/workspace/repo")

    def __init__(
        self,
        github_client: GitHubClient,
        settings: Settings,
    ) -> None:
        self.github = github_client
        self.settings = settings
        self.current_branch: str | None = None

    def get_workspace(self) -> Path:
        """Get workspace path (repo is pre-cloned by entrypoint)."""
        return self.REPO_PATH


def create_tools(ctx: ToolContext) -> list:
    """Create tools with the given context."""

    # =============================================================================
    # File System Tools
    # =============================================================================

    def list_repository_files(directory: str = ".") -> str:
        """List files in the repository directory."""
        workspace = ctx.get_workspace()

        try:
            target = workspace / directory
            if not target.exists():
                return f"Directory not found: {directory}"

            items = []
            for item in sorted(target.iterdir()):
                if item.name.startswith("."):
                    continue
                prefix = "📁" if item.is_dir() else "📄"
                items.append(f"{prefix} {item.relative_to(workspace)}")

            return "\n".join(items) if items else "Directory is empty"
        except Exception as e:
            return f"Error listing files: {e}"

    def read_file(filepath: str) -> str:
        """Read contents of a file from the repository."""
        workspace = ctx.get_workspace()

        try:
            file_path = workspace / filepath
            if file_path.exists():
                return file_path.read_text(encoding="utf-8")

            # Try reading from GitHub if not cloned
            content = ctx.github.get_file_content(filepath)
            if content:
                return content

            return f"File not found: {filepath}"
        except Exception as e:
            return f"Error reading file: {e}"

    def write_file(filepath: str, content: str) -> str:
        """Write or update a file in the repository."""
        workspace = ctx.get_workspace()

        try:
            file_path = workspace / filepath
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding="utf-8")
            logger.info("file_written", filepath=filepath)
            return f"File written successfully: {filepath}"
        except Exception as e:
            return f"Error writing file: {e}"

    def search_code(pattern: str, file_glob: str = "*.py") -> str:
        """Search for a pattern in repository files."""
        workspace = ctx.get_workspace()

        try:
            results = []
            for filepath in workspace.rglob(file_glob):
                if ".git" in str(filepath):
                    continue
                try:
                    content = filepath.read_text(encoding="utf-8")
                    for i, line in enumerate(content.splitlines(), 1):
                        if pattern.lower() in line.lower():
                            rel_path = filepath.relative_to(workspace)
                            results.append(f"{rel_path}:{i}: {line.strip()}")
                except Exception:
                    continue

            if not results:
                return f"No matches found for '{pattern}'"

            return "\n".join(results[:50])
        except Exception as e:
            return f"Error searching: {e}"

    # =============================================================================
    # Git Tools
    # =============================================================================

    def create_branch(branch_name: str) -> str:
        """Create and checkout a new git branch."""
        from git import Repo

        workspace = ctx.get_workspace()

        try:
            repo = Repo(workspace)
            repo.git.checkout("-b", branch_name)
            ctx.current_branch = branch_name
            logger.info("branch_created", branch=branch_name)
            return f"Created and checked out branch: {branch_name}"
        except Exception as e:
            return f"Error creating branch: {e}"

    def commit_changes(message: str) -> str:
        """Stage all changes and create a commit."""
        from git import Repo

        workspace = ctx.get_workspace()

        try:
            repo = Repo(workspace)
            repo.git.add("-A")

            if not repo.index.diff("HEAD") and not repo.untracked_files:
                return "No changes to commit"

            repo.index.commit(message)
            logger.info("changes_committed", message=message)
            return f"Changes committed: {message}"
        except Exception as e:
            return f"Error committing: {e}"

    def push_changes() -> str:
        """Push current branch to remote."""
        from git import Repo

        workspace = ctx.get_workspace()
        if not ctx.current_branch:
            return "Error: No branch set. Use create_branch first."

        try:
            repo = Repo(workspace)
            repo.git.push("--set-upstream", "origin", ctx.current_branch, "--force")
            logger.info("changes_pushed", branch=ctx.current_branch)
            return f"Pushed to origin/{ctx.current_branch}"
        except Exception as e:
            return f"Error pushing: {e}"

    # =============================================================================
    # GitHub Tools
    # =============================================================================

    def get_issue(issue_number: int) -> str:
        """Get details of a GitHub issue."""
        try:
            issue = ctx.github.get_issue(issue_number)
            return f"""## Issue #{issue.number}: {issue.title}

**State:** {issue.state}
**Labels:** {', '.join([l.name for l in issue.labels]) or 'None'}

### Description:
{issue.body or 'No description'}
"""
        except Exception as e:
            return f"Error fetching issue: {e}"

    def create_pull_request(title: str, body: str, head_branch: str) -> str:
        """Create a pull request on GitHub."""
        try:
            pr = ctx.github.repo.create_pull(
                title=title,
                body=body,
                head=head_branch,
                base=ctx.github.repo.default_branch,
            )
            logger.info("pr_created", number=pr.number, url=pr.html_url)
            return f"Pull request created: {pr.html_url}"
        except Exception as e:
            return f"Error creating PR: {e}"

    def get_pr_status(pr_number: int) -> str:
        """Get status of a pull request including CI checks."""
        try:
            pr = ctx.github.repo.get_pull(pr_number)
            commit = ctx.github.repo.get_commit(pr.head.sha)
            checks = list(commit.get_check_runs())

            status_lines = [
                f"## PR #{pr.number}: {pr.title}",
                f"**State:** {pr.state}",
                f"**Mergeable:** {pr.mergeable}",
                "",
                "### CI Checks:",
            ]

            if checks:
                for check in checks:
                    icon = "✅" if check.conclusion == "success" else "❌" if check.conclusion == "failure" else "🔄"
                    status_lines.append(f"  {icon} {check.name}: {check.conclusion or 'running'}")
            else:
                status_lines.append("  No checks found")

            return "\n".join(status_lines)
        except Exception as e:
            return f"Error getting PR status: {e}"

    # =============================================================================
    # Code Execution Tools
    # =============================================================================

    def run_command(command: str) -> str:
        """Run a shell command in the repository directory. Only allowed: pytest, ruff, black, mypy, pip"""
        workspace = ctx.get_workspace()

        allowed_prefixes = ["pytest", "ruff", "black", "mypy", "pip install", "python -m pytest"]
        if not any(command.strip().startswith(p) for p in allowed_prefixes):
            return f"Error: Command not allowed. Allowed: {allowed_prefixes}"

        try:
            result = subprocess.run(
                command,
                shell=True,
                cwd=workspace,
                capture_output=True,
                text=True,
                timeout=120,
            )
            output = result.stdout + result.stderr
            return output[:5000] if output else "Command completed with no output"
        except subprocess.TimeoutExpired:
            return "Error: Command timed out (120s limit)"
        except Exception as e:
            return f"Error running command: {e}"

    # =============================================================================
    # Build Tool List
    # =============================================================================

    return [
        StructuredTool.from_function(
            func=list_repository_files,
            name="list_repository_files",
            description="List files in the repository directory. Args: directory (str, default='.')",
        ),
        StructuredTool.from_function(
            func=read_file,
            name="read_file",
            description="Read contents of a file from the repository. Args: filepath (str)",
        ),
        StructuredTool.from_function(
            func=write_file,
            name="write_file",
            description="Write or update a file in the repository. Args: filepath (str), content (str)",
        ),
        StructuredTool.from_function(
            func=search_code,
            name="search_code",
            description="Search for a pattern in repository files. Args: pattern (str), file_glob (str, default='*.py')",
        ),
        StructuredTool.from_function(
            func=create_branch,
            name="create_branch",
            description="Create and checkout a new git branch. Args: branch_name (str)",
        ),
        StructuredTool.from_function(
            func=commit_changes,
            name="commit_changes",
            description="Stage all changes and create a commit. Args: message (str)",
        ),
        StructuredTool.from_function(
            func=push_changes,
            name="push_changes",
            description="Push current branch to remote. No args.",
        ),
        StructuredTool.from_function(
            func=get_issue,
            name="get_issue",
            description="Get details of a GitHub issue. Args: issue_number (int)",
        ),
        StructuredTool.from_function(
            func=create_pull_request,
            name="create_pull_request",
            description="Create a pull request on GitHub. Args: title (str), body (str), head_branch (str)",
        ),
        StructuredTool.from_function(
            func=get_pr_status,
            name="get_pr_status",
            description="Get status of a pull request including CI checks. Args: pr_number (int)",
        ),
        StructuredTool.from_function(
            func=run_command,
            name="run_command",
            description="Run a shell command (only pytest, ruff, black, mypy, pip allowed). Args: command (str)",
        ),
    ]
