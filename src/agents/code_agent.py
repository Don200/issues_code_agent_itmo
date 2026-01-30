"""Code Agent - generates code based on GitHub issues using LangChain tools."""

import re
from pathlib import Path
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
    """
    Agent responsible for analyzing issues and generating code.

    Uses LangChain with tool calling for:
    - Reading and understanding the codebase
    - Generating and writing code changes
    - Running tests and linting
    - Creating commits and pull requests
    """

    def __init__(
        self,
        settings: Settings,
        github_client: GitHubClient,
    ) -> None:
        self._settings = settings
        self._github = github_client
        self._llm = create_llm(settings)
        self._log = logger.bind(component="code_agent")

        # Create tool context and tools
        self._tool_ctx = ToolContext(github_client, settings)
        self._tools = create_tools(self._tool_ctx)

    def process_issue(self, issue_number: int) -> dict[str, Any]:
        """
        Process a GitHub issue end-to-end using the agent loop.

        Args:
            issue_number: GitHub issue number to process

        Returns:
            Dict with processing results
        """
        self._log.info("processing_issue", issue_number=issue_number)

        # Create the task prompt for the agent
        task_prompt = f"""Process GitHub Issue #{issue_number}:

Your task:
1. Read and understand the issue requirements
2. Explore the codebase to understand the context
3. Implement the required changes
4. Run tests to verify your changes work
5. Create a PR with your changes

Start by getting the issue details and cloning the repository.
"""

        try:
            # Run the agent loop
            result = run_agent_loop(
                llm=self._llm,
                tools=self._tools,
                system_prompt=CODE_AGENT_SYSTEM_PROMPT,
                user_message=task_prompt,
                max_iterations=self._settings.max_iterations * 10,  # More iterations for complex tasks
            )

            # Parse result to extract PR info
            pr_info = self._extract_pr_info(result)

            return {
                "success": True,
                "issue_number": issue_number,
                "pr_number": pr_info.get("pr_number"),
                "pr_url": pr_info.get("pr_url"),
                "branch": pr_info.get("branch"),
                "files_changed": pr_info.get("files_changed", []),
                "agent_summary": result,
            }

        except Exception as e:
            self._log.error(
                "issue_processing_failed",
                issue_number=issue_number,
                error=str(e),
            )
            raise CodeGenerationError(
                f"Failed to process issue: {e}",
                details={"issue_number": issue_number, "error": str(e)},
            ) from e

    def fix_based_on_review(
        self,
        issue_number: int,
        pr_number: int,
        review_feedback: str,
        iteration: int,
    ) -> dict[str, Any]:
        """
        Fix code based on review feedback using the agent loop.

        Args:
            issue_number: Original issue number
            pr_number: PR number being fixed
            review_feedback: Review feedback to address
            iteration: Current iteration number

        Returns:
            Dict with fix results
        """
        self._log.info(
            "fixing_based_on_review",
            issue_number=issue_number,
            pr_number=pr_number,
            iteration=iteration,
        )

        task_prompt = f"""Fix PR #{pr_number} based on review feedback.

## Original Issue: #{issue_number}

## Review Feedback (Iteration {iteration}):
{review_feedback}

## Your Task:
1. Check the current PR status with `get_pr_status({pr_number})`
2. Read the original issue requirements with `get_issue({issue_number})`
3. Read the relevant files that need fixing
4. Make the necessary fixes based on the feedback
5. Run tests to verify your fixes
6. Commit and push the changes

Note: The branch already exists, you just need to make fixes and push.
"""

        try:
            result = run_agent_loop(
                llm=self._llm,
                tools=self._tools,
                system_prompt=CODE_AGENT_SYSTEM_PROMPT,
                user_message=task_prompt,
                max_iterations=self._settings.max_iterations * 5,
            )

            return {
                "success": True,
                "iteration": iteration,
                "files_changed": self._extract_changed_files(result),
                "summary": result,
            }

        except Exception as e:
            self._log.error(
                "fix_failed",
                pr_number=pr_number,
                iteration=iteration,
                error=str(e),
            )
            raise

    def _extract_pr_info(self, agent_result: str) -> dict[str, Any]:
        """Extract PR information from agent result."""
        info: dict[str, Any] = {}

        # Try to find PR URL
        pr_url_match = re.search(r"https://github\.com/[^/]+/[^/]+/pull/(\d+)", agent_result)
        if pr_url_match:
            info["pr_url"] = pr_url_match.group(0)
            info["pr_number"] = int(pr_url_match.group(1))

        # Try to find branch name
        branch_match = re.search(r"branch[:\s]+[`'\"]?([a-zA-Z0-9_/-]+)[`'\"]?", agent_result, re.IGNORECASE)
        if branch_match:
            info["branch"] = branch_match.group(1)

        # Try to find changed files
        info["files_changed"] = self._extract_changed_files(agent_result)

        return info

    def _extract_changed_files(self, agent_result: str) -> list[str]:
        """Extract list of changed files from agent result."""
        files = []

        # Look for file paths in the result
        file_patterns = [
            r"(?:wrote|created|modified|updated)[:\s]+[`'\"]?([a-zA-Z0-9_/.-]+\.[a-z]+)[`'\"]?",
            r"File (?:written|created)[:\s]+[`'\"]?([a-zA-Z0-9_/.-]+\.[a-z]+)[`'\"]?",
        ]

        for pattern in file_patterns:
            matches = re.findall(pattern, agent_result, re.IGNORECASE)
            files.extend(matches)

        return list(set(files))
