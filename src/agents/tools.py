"""Minimal tools for the SDLC Agent MVP."""

from pathlib import Path

import structlog
from langchain_core.tools import StructuredTool

from src.core.config import Settings
from src.github.client import GitHubClient

logger = structlog.get_logger()


class ToolContext:
    """Context holding dependencies for tools."""

    REPO_PATH = Path("/app/workspace/repo")

    def __init__(
        self,
        github_client: GitHubClient,
        settings: Settings,
    ) -> None:
        self.github = github_client
        self.settings = settings
        self.current_branch: str | None = None
        self.task_finished = False
        self.finish_message: str | None = None

    def get_workspace(self) -> Path:
        """Get workspace path."""
        return self.REPO_PATH


def create_tools(ctx: ToolContext) -> list:
    """Create minimal set of tools for MVP."""

    # =========================================================================
    # FINISH TOOL - Most important! Agent must call this to complete.
    # =========================================================================

    def finish(summary: str) -> str:
        """
        Call this when the task is COMPLETE. Provide a summary of what was done.

        Args:
            summary: Brief summary of completed work
        """
        ctx.task_finished = True
        ctx.finish_message = summary
        logger.info("🏁 TASK FINISHED", summary=summary)
        return f"Task completed: {summary}"

    # =========================================================================
    # GitHub Tools
    # =========================================================================

    def get_issue(issue_number: int) -> str:
        """Get details of a GitHub issue to understand the task."""
        try:
            issue = ctx.github.get_issue(issue_number)
            result = f"""## Issue #{issue.number}: {issue.title}

**State:** {issue.state}
**Labels:** {', '.join([l.name for l in issue.labels]) or 'None'}

### Description:
{issue.body or 'No description'}
"""
            logger.info("📋 Got issue", number=issue_number, title=issue.title)
            return result
        except Exception as e:
            logger.error("❌ Failed to get issue", error=str(e))
            return f"Error: {e}"

    # =========================================================================
    # File Tools
    # =========================================================================

    def list_files(directory: str = ".") -> str:
        """List files in directory to understand project structure."""
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

            result = "\n".join(items[:50]) if items else "Empty directory"
            logger.info("📂 Listed files", directory=directory, count=len(items))
            return result
        except Exception as e:
            logger.error("❌ Failed to list files", error=str(e))
            return f"Error: {e}"

    def read_file(filepath: str) -> str:
        """Read a file to understand existing code."""
        workspace = ctx.get_workspace()

        try:
            file_path = workspace / filepath
            if file_path.exists():
                content = file_path.read_text(encoding="utf-8")
                logger.info("📖 Read file", filepath=filepath, lines=len(content.splitlines()))
                return content

            # Fallback to GitHub API
            content = ctx.github.get_file_content(filepath)
            if content:
                logger.info("📖 Read file from GitHub", filepath=filepath)
                return content

            return f"File not found: {filepath}"
        except Exception as e:
            logger.error("❌ Failed to read file", filepath=filepath, error=str(e))
            return f"Error: {e}"

    def write_file(filepath: str, content: str) -> str:
        """Write or update a file. Always write COMPLETE file content."""
        workspace = ctx.get_workspace()

        try:
            file_path = workspace / filepath
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding="utf-8")
            logger.info("✏️ Wrote file", filepath=filepath, lines=len(content.splitlines()))
            return f"✅ File written: {filepath}"
        except Exception as e:
            logger.error("❌ Failed to write file", filepath=filepath, error=str(e))
            return f"Error: {e}"

    # =========================================================================
    # Git Tools
    # =========================================================================

    def create_branch(branch_name: str) -> str:
        """Create a new git branch for your changes."""
        from git import Repo

        workspace = ctx.get_workspace()

        try:
            repo = Repo(workspace)
            repo.git.checkout("-b", branch_name)
            ctx.current_branch = branch_name
            logger.info("🌿 Created branch", branch=branch_name)
            return f"✅ Branch created: {branch_name}"
        except Exception as e:
            logger.error("❌ Failed to create branch", error=str(e))
            return f"Error: {e}"

    def commit_and_push(message: str) -> str:
        """Commit all changes and push to remote."""
        from git import Repo

        workspace = ctx.get_workspace()

        if not ctx.current_branch:
            return "Error: Create a branch first with create_branch()"

        try:
            repo = Repo(workspace)
            repo.git.add("-A")

            # Check if there are changes
            if not repo.index.diff("HEAD") and not repo.untracked_files:
                return "No changes to commit"

            repo.index.commit(message)

            # Push with token authentication
            remote_url = f"https://x-access-token:{ctx.settings.github_token}@github.com/{ctx.settings.github_repository}.git"
            repo.git.push(remote_url, f"HEAD:{ctx.current_branch}", "--force")

            logger.info("📤 Committed and pushed", branch=ctx.current_branch, message=message)
            return f"✅ Pushed to {ctx.current_branch}"
        except Exception as e:
            logger.error("❌ Failed to commit/push", error=str(e))
            return f"Error: {e}"

    def create_pull_request(title: str, body: str) -> str:
        """Create a pull request with your changes."""
        if not ctx.current_branch:
            return "Error: You must create_branch() and commit_and_push() first!"

        # Check if branch exists on remote
        try:
            ctx.github.repo.get_branch(ctx.current_branch)
        except Exception:
            return f"Error: Branch '{ctx.current_branch}' not found on GitHub. Did you call commit_and_push()?"

        try:
            pr = ctx.github.repo.create_pull(
                title=title,
                body=body,
                head=ctx.current_branch,
                base=ctx.github.repo.default_branch,
            )
            logger.info("🔀 Created PR", number=pr.number, url=pr.html_url)
            return f"✅ PR created: {pr.html_url}"
        except Exception as e:
            logger.error("❌ Failed to create PR", error=str(e))
            return f"Error: {e}"

    # =========================================================================
    # Build Tool List
    # =========================================================================

    return [
        # Must call this when done!
        StructuredTool.from_function(
            func=finish,
            name="finish",
            description="REQUIRED: Call this when task is complete with a summary of what was done.",
        ),
        # GitHub
        StructuredTool.from_function(
            func=get_issue,
            name="get_issue",
            description="Get GitHub issue details. Args: issue_number (int)",
        ),
        # Files
        StructuredTool.from_function(
            func=list_files,
            name="list_files",
            description="List files in directory. Args: directory (str, default='.')",
        ),
        StructuredTool.from_function(
            func=read_file,
            name="read_file",
            description="Read file contents. Args: filepath (str)",
        ),
        StructuredTool.from_function(
            func=write_file,
            name="write_file",
            description="Write complete file content. Args: filepath (str), content (str)",
        ),
        # Git
        StructuredTool.from_function(
            func=create_branch,
            name="create_branch",
            description="Create git branch. Args: branch_name (str)",
        ),
        StructuredTool.from_function(
            func=commit_and_push,
            name="commit_and_push",
            description="Commit all changes and push. Args: message (str)",
        ),
        StructuredTool.from_function(
            func=create_pull_request,
            name="create_pull_request",
            description="Create PR. Args: title (str), body (str)",
        ),
    ]
