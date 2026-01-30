"""Code Agent - MVP version with tool calling."""

import re
from typing import Any

import structlog

from src.agents.agent_loop import (
    CODE_AGENT_SYSTEM_PROMPT,
    create_llm,
    run_agent_loop,
)
from src.agents.tools import ToolContext, create_tools
from src.core.config import Settings
from src.core.exceptions import CodeGenerationError
from src.github.client import GitHubClient

logger = structlog.get_logger()


class CodeAgent:
    """Agent that implements GitHub issues using tool calling."""

    def __init__(
        self,
        settings: Settings,
        github_client: GitHubClient,
    ) -> None:
        self._settings = settings
        self._github = github_client
        self._llm = create_llm(settings)

        # Create tool context and tools
        self._tool_ctx = ToolContext(github_client, settings)
        self._tools = create_tools(self._tool_ctx)

    def process_issue(self, issue_number: int, max_iterations: int = 15) -> dict[str, Any]:
        """Process a GitHub issue and create a PR."""
        logger.info("Processing issue", issue_number=issue_number, max_iterations=max_iterations)

        # Reset context for new task
        self._tool_ctx.task_finished = False
        self._tool_ctx.finish_message = None
        self._tool_ctx.current_branch = None

        task = f"Implement GitHub Issue #{issue_number}. Follow the workflow: get issue → explore code → create branch → implement → commit → create PR → finish."

        try:
            result = run_agent_loop(
                llm=self._llm,
                tools=self._tools,
                system_prompt=CODE_AGENT_SYSTEM_PROMPT,
                user_message=task,
                tool_context=self._tool_ctx,
                max_iterations=max_iterations,
            )

            return {
                "success": self._tool_ctx.task_finished,
                "issue_number": issue_number,
                "branch": self._tool_ctx.current_branch,
                "summary": result,
            }

        except Exception as e:
            logger.error("Failed to process issue", error=str(e))
            raise CodeGenerationError(
                f"Failed to process issue: {e}",
                details={"issue_number": issue_number},
            ) from e

    def fix_based_on_review(
        self,
        issue_number: int,
        pr_number: int,
        review_feedback: str,
        iteration: int,
    ) -> dict[str, Any]:
        """Fix code based on review feedback."""
        logger.info("Fixing based on review", pr_number=pr_number, iteration=iteration)

        # Reset finish flag
        self._tool_ctx.task_finished = False
        self._tool_ctx.finish_message = None

        task = f"""Fix PR #{pr_number} based on review feedback.

Issue: #{issue_number}
Iteration: {iteration}

Feedback:
{review_feedback}

Read the relevant files, make fixes, commit and push. Then call finish().
"""

        try:
            result = run_agent_loop(
                llm=self._llm,
                tools=self._tools,
                system_prompt=CODE_AGENT_SYSTEM_PROMPT,
                user_message=task,
                tool_context=self._tool_ctx,
                max_iterations=10,
            )

            return {
                "success": self._tool_ctx.task_finished,
                "iteration": iteration,
                "summary": result,
            }

        except Exception as e:
            logger.error("Failed to fix", error=str(e))
            raise
