"""Simple Agent Loop with LangChain - MVP version."""

from typing import Any

import structlog
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI
from rich.console import Console
from rich.panel import Panel

from src.core.config import Settings

logger = structlog.get_logger()
console = Console()

# Reasonable limit for MVP
MAX_ITERATIONS = 15


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
    user_message: str,
    tool_context: Any = None,
    max_iterations: int = MAX_ITERATIONS,
) -> str:
    """
    Run agent loop until task is complete or max iterations.

    Args:
        llm: LangChain LLM
        tools: List of tools
        system_prompt: System prompt
        user_message: Task description
        tool_context: ToolContext to check task_finished flag
        max_iterations: Max iterations before giving up

    Returns:
        Final result message
    """
    llm_with_tools = llm.bind_tools(tools)
    tools_by_name = {t.name: t for t in tools}

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_message),
    ]

    console.print(Panel(user_message, title="📋 Task", border_style="blue"))

    for iteration in range(1, max_iterations + 1):
        console.print(f"\n[bold cyan]── Iteration {iteration}/{max_iterations} ──[/bold cyan]")

        # Call LLM
        try:
            response = llm_with_tools.invoke(messages)
        except Exception as e:
            console.print(f"[red]LLM Error: {e}[/red]")
            raise

        messages.append(response)

        # Check if agent wants to respond without tools (done thinking)
        if not response.tool_calls:
            console.print("[green]Agent finished (no more tool calls)[/green]")
            return response.content or "Task completed"

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

            messages.append(ToolMessage(content=str(result), tool_call_id=tool_id))

            # Check if finish was called
            if tool_context and tool_context.task_finished:
                console.print("\n[bold green]✅ Task completed![/bold green]")
                return tool_context.finish_message or "Task completed"

    console.print(f"\n[bold red]⚠️ Max iterations ({max_iterations}) reached[/bold red]")
    return "Task incomplete: reached maximum iterations"


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

IMPORTANT: You MUST call the `finish` tool when done!

## Tools:
- get_issue(issue_number) - Get task details
- list_files(directory) - See project structure
- read_file(filepath) - Read file content
- write_file(filepath, content) - Write COMPLETE file content
- create_branch(branch_name) - Create git branch
- commit_and_push(message) - Commit and push changes
- create_pull_request(title, body) - Create PR
- finish(summary) - CALL THIS WHEN DONE

## Workflow:
1. get_issue() - understand the task
2. list_files() - explore structure
3. read_file() - read relevant files
4. create_branch() - create branch like "issue-123-add-feature"
5. write_file() - make changes (write FULL file content!)
6. commit_and_push() - save changes
7. create_pull_request() - open PR
8. finish() - summarize what you did

## Rules:
- Always write COMPLETE file content, not snippets
- Always call finish() at the end
"""

REVIEW_AGENT_SYSTEM_PROMPT = """You are a code reviewer. Review the PR and provide feedback.

Call finish() with your decision: APPROVED or CHANGES_REQUESTED with explanation.
"""
