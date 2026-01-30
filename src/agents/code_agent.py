"""Code Agent - MVP version with tool calling."""

from typing import Any

import structlog

from src.agents.agent_loop import (
    CODE_AGENT_SYSTEM_PROMPT,
    AgentState,
    create_llm,
    run_agent_loop,
)
from src.agents.tools import ToolContext, create_tools
from src.core.config import Settings
from src.core.exceptions import CodeGenerationError
from src.github.client import GitHubClient

logger = structlog.get_logger()


class CodeAgent:
    """Agent that implements GitHub issues using tool calling.

    Maintains state between calls for multi-iteration workflows.
    """

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

        # Agent state - persists between calls
        self._state: AgentState | None = None

    def process_issue(self, issue_number: int, max_iterations: int = 15) -> dict[str, Any]:
        """Process a GitHub issue and create a PR.

        This starts a new agent conversation. The state is preserved
        for subsequent continue_with_feedback() calls.
        """
        logger.info("Processing issue", issue_number=issue_number, max_iterations=max_iterations)

        # Reset context for new task
        self._tool_ctx.task_finished = False
        self._tool_ctx.finish_message = None
        self._tool_ctx.current_branch = None
        self._state = None  # Fresh state

        task = f"Implement GitHub Issue #{issue_number}. Follow the workflow: get issue → explore code → create branch → implement → commit → create PR → finish."

        try:
            result, self._state = run_agent_loop(
                llm=self._llm,
                tools=self._tools,
                system_prompt=CODE_AGENT_SYSTEM_PROMPT,
                user_message=task,
                tool_context=self._tool_ctx,
                max_iterations=max_iterations,
                state=None,  # New conversation
            )

            return {
                "success": self._tool_ctx.task_finished,
                "issue_number": issue_number,
                "branch": self._state.branch or self._tool_ctx.current_branch,
                "pr_number": self._state.pr_number,
                "pr_url": self._state.pr_url,
                "summary": result,
            }

        except Exception as e:
            logger.error("Failed to process issue", error=str(e))
            raise CodeGenerationError(
                f"Failed to process issue: {e}",
                details={"issue_number": issue_number},
            ) from e

    def continue_with_feedback(
        self,
        feedback: str,
        max_iterations: int = 10,
    ) -> dict[str, Any]:
        """Continue the agent with CI/review feedback.

        This continues the existing conversation - the agent remembers
        everything it did before and just receives new feedback.
        """
        if not self._state:
            raise CodeGenerationError(
                "No active agent state. Call process_issue() first.",
                details={},
            )

        logger.info(
            "Continuing with feedback",
            branch=self._state.branch,
            pr_number=self._state.pr_number,
        )

        # Reset finish flag for new iteration
        self._tool_ctx.task_finished = False
        self._tool_ctx.finish_message = None

        try:
            result, self._state = run_agent_loop(
                llm=self._llm,
                tools=self._tools,
                system_prompt=CODE_AGENT_SYSTEM_PROMPT,
                user_message=feedback,
                tool_context=self._tool_ctx,
                max_iterations=max_iterations,
                state=self._state,  # Continue existing conversation
            )

            return {
                "success": self._tool_ctx.task_finished,
                "branch": self._state.branch,
                "pr_number": self._state.pr_number,
                "summary": result,
            }

        except Exception as e:
            logger.error("Failed to apply fixes", error=str(e))
            raise

    @property
    def state(self) -> AgentState | None:
        """Current agent state."""
        return self._state

    def reset(self) -> None:
        """Reset agent state for a new task."""
        self._state = None
        self._tool_ctx.task_finished = False
        self._tool_ctx.finish_message = None
        self._tool_ctx.current_branch = None
