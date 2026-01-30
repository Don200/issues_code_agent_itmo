"""Simple Agent Loop with LangChain - MVP version."""

from dataclasses import dataclass, field
from typing import Any

import structlog
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI
from rich.console import Console
from rich.panel import Panel

from src.core.config import Settings

logger = structlog.get_logger()
console = Console()

# Reasonable limit for MVP
MAX_ITERATIONS = 15


@dataclass
class AgentState:
    """Persistent agent state between iterations."""
    messages: list[BaseMessage] = field(default_factory=list)
    branch: str | None = None
    pr_number: int | None = None
    pr_url: str | None = None
    finished: bool = False
    finish_message: str | None = None


def create_llm(settings: Settings) -> ChatOpenAI:
    """Create LangChain ChatOpenAI instance."""
    kwargs: dict[str, Any] = {
        "model": settings.openai_model,
        "api_key": settings.openai_api_key,
        "temperature": 0.2,  # Low for more predictable behavior
        "max_tokens": settings.openai_max_tokens,
    }

    if settings.openai_base_url:
        kwargs["base_url"] = settings.openai_base_url

    # Add Langfuse if configured
    if settings.langfuse_enabled:
        try:
            from langfuse.callback import CallbackHandler
            handler = CallbackHandler(
                public_key=settings.langfuse_public_key,
                secret_key=settings.langfuse_secret_key,
                host=settings.langfuse_base_url,
            )
            kwargs["callbacks"] = [handler]
            console.print("[dim]Langfuse: enabled[/dim]")
        except Exception as e:
            console.print(f"[dim]Langfuse: failed ({e})[/dim]")

    console.print(f"[dim]Model: {settings.openai_model}[/dim]")
    return ChatOpenAI(**kwargs)


def run_agent_loop(
    llm: ChatOpenAI,
    tools: list,
    system_prompt: str,
    user_message: str | None = None,
    tool_context: Any = None,
    max_iterations: int = MAX_ITERATIONS,
    state: AgentState | None = None,
) -> tuple[str, AgentState]:
    """
    Run agent loop until task is complete or max iterations.

    Args:
        llm: LangChain LLM
        tools: List of tools
        system_prompt: System prompt
        user_message: Task description (for new conversation) or feedback (for continuation)
        tool_context: ToolContext to check task_finished flag
        max_iterations: Max iterations before giving up
        state: Existing state to continue from (None = new conversation)

    Returns:
        Tuple of (result message, updated state)
    """
    llm_with_tools = llm.bind_tools(tools)
    tools_by_name = {t.name: t for t in tools}

    # Initialize or continue state
    if state is None:
        state = AgentState()
        state.messages = [SystemMessage(content=system_prompt)]

    # Add new user message if provided
    if user_message:
        state.messages.append(HumanMessage(content=user_message))
        console.print(Panel(user_message, title="📋 Task", border_style="blue"))

    for iteration in range(1, max_iterations + 1):
        console.print(f"\n[bold cyan]── Iteration {iteration}/{max_iterations} ──[/bold cyan]")

        # Call LLM
        try:
            response = llm_with_tools.invoke(state.messages)
        except Exception as e:
            console.print(f"[red]LLM Error: {e}[/red]")
            raise

        state.messages.append(response)

        # Check if agent wants to respond without tools (done thinking)
        if not response.tool_calls:
            console.print("[green]Agent finished (no more tool calls)[/green]")
            return response.content or "Task completed", state

        # Execute each tool call
        for tool_call in response.tool_calls:
            tool_name = tool_call["name"]
            tool_args = tool_call["args"]
            tool_id = tool_call["id"]

            console.print(f"  🔧 [yellow]{tool_name}[/yellow]({_format_args(tool_args)})")

            if tool_name not in tools_by_name:
                result = f"Error: Unknown tool '{tool_name}'"
                console.print(f"     [red]{result}[/red]")
            else:
                try:
                    result = tools_by_name[tool_name].invoke(tool_args)
                    # Truncate long results for display
                    display_result = str(result)[:200] + "..." if len(str(result)) > 200 else str(result)
                    console.print(f"     [dim]{display_result}[/dim]")
                except Exception as e:
                    result = f"Error: {e}"
                    console.print(f"     [red]{result}[/red]")

            state.messages.append(ToolMessage(content=str(result), tool_call_id=tool_id))

            # Track branch and PR from tool results
            if tool_name == "create_branch" and not result.startswith("Error"):
                state.branch = tool_args.get("branch_name")
            elif tool_name == "create_pull_request" and "PR created" in result:
                # Extract PR URL from result like "✅ PR created: https://..."
                import re
                if match := re.search(r"https://[^\s]+/pull/(\d+)", result):
                    state.pr_url = match.group(0)
                    state.pr_number = int(match.group(1))

            # Check if finish was called
            if tool_context and tool_context.task_finished:
                console.print("\n[bold green]✅ Task completed![/bold green]")
                state.finished = True
                state.finish_message = tool_context.finish_message
                return tool_context.finish_message or "Task completed", state

    console.print(f"\n[bold red]⚠️ Max iterations ({max_iterations}) reached[/bold red]")
    return "Task incomplete: reached maximum iterations", state


def _format_args(args: dict) -> str:
    """Format tool arguments for display."""
    if not args:
        return ""
    parts = []
    for k, v in args.items():
        if isinstance(v, str) and len(v) > 50:
            v = v[:50] + "..."
        parts.append(f"{k}={repr(v)}")
    return ", ".join(parts)


# =============================================================================
# System Prompts - Simple and clear
# =============================================================================

CODE_AGENT_SYSTEM_PROMPT = """You are a coding agent. Complete the task using the available tools.

## Tools:
- get_issue(issue_number) - Get task details
- get_ci_logs(pr_number) - Get CI logs to see why tests failed
- list_files(directory) - See project structure
- read_file(filepath) - Read file content
- write_file(filepath, content) - Write COMPLETE file content
- create_branch(branch_name) - Create NEW git branch
- switch_branch(branch_name) - Switch to EXISTING branch
- commit_and_push(message) - Commit all changes and push
- create_pull_request(title, body) - Create PR (REQUIRED!)
- finish(summary) - Call when done

## Workflow (MUST follow in order):
1. get_issue() - understand the task
2. list_files() / read_file() - explore codebase
3. create_branch() - create branch like "issue-123-description"
4. write_file() - implement changes (write FULL file content!)
5. commit_and_push() - commit and push changes
6. create_pull_request() - REQUIRED! Create PR for review
7. finish() - summarize what you did

## IMPORTANT RULES:
- You MUST create a Pull Request before calling finish()
- Always write COMPLETE file content, not snippets
- Do NOT call finish() until PR is created successfully
- If fixing existing PR: use get_ci_logs() to see errors, fix code, commit, push, finish (no new PR/branch)
"""

REVIEW_AGENT_SYSTEM_PROMPT = """You are a code reviewer. Review the PR and provide feedback.

Call finish() with your decision: APPROVED or CHANGES_REQUESTED with explanation.
"""
