"""Agent Loop - LangChain-based agentic execution with tool calling."""

from typing import Any

import structlog
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage, AIMessage
from langchain_openai import ChatOpenAI

from src.core.config import Settings

logger = structlog.get_logger()

# Maximum iterations to prevent infinite loops
MAX_ITERATIONS = 50


def _get_langfuse_handler(settings: Settings) -> Any | None:
    """Get Langfuse callback handler if configured."""
    if not settings.langfuse_enabled:
        logger.info("langfuse_disabled", reason="Keys not configured")
        return None

    try:
        from langfuse.callback import CallbackHandler

        handler = CallbackHandler(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_base_url,
        )
        logger.info("langfuse_enabled", host=settings.langfuse_base_url or "cloud")
        return handler
    except Exception as e:
        logger.warning("langfuse_init_failed", error=str(e))
        return None


def create_llm(settings: Settings) -> ChatOpenAI:
    """Create LangChain ChatOpenAI instance with Langfuse if configured."""
    kwargs: dict[str, Any] = {
        "model": settings.openai_model,
        "api_key": settings.openai_api_key,
        "temperature": 0.3,
        "max_tokens": settings.openai_max_tokens,
    }

    if settings.openai_base_url:
        kwargs["base_url"] = settings.openai_base_url

    # Add Langfuse callback if available
    langfuse_handler = _get_langfuse_handler(settings)
    if langfuse_handler:
        kwargs["callbacks"] = [langfuse_handler]

    logger.info(
        "llm_initialized",
        model=settings.openai_model,
        base_url=settings.openai_base_url or "default",
        langfuse=langfuse_handler is not None,
    )

    return ChatOpenAI(**kwargs)


def run_agent_loop(
    llm: ChatOpenAI,
    tools: list,
    system_prompt: str,
    user_message: str,
    max_iterations: int = MAX_ITERATIONS,
) -> str:
    """
    Run the agent loop with tool calling.

    Args:
        llm: LangChain LLM instance
        tools: List of tools available to the agent
        system_prompt: System prompt for the agent
        user_message: Initial user message/task
        max_iterations: Maximum number of iterations

    Returns:
        Final agent response
    """
    # Bind tools to LLM
    llm_with_tools = llm.bind_tools(tools)
    tools_by_name = {t.name: t for t in tools}

    # Initialize message history
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_message),
    ]

    iteration = 0
    while iteration < max_iterations:
        iteration += 1
        logger.debug(
            "agent_iteration",
            iteration=iteration,
            messages_count=len(messages),
        )

        # Call LLM
        try:
            response = llm_with_tools.invoke(messages)
        except Exception as e:
            logger.error("llm_call_failed", error=str(e))
            raise

        messages.append(response)

        # Check if agent is done (no tool calls)
        if not response.tool_calls:
            logger.info(
                "agent_completed",
                iterations=iteration,
                response_length=len(response.content),
            )
            return response.content

        # Execute tool calls
        for tool_call in response.tool_calls:
            tool_name = tool_call["name"]
            tool_args = tool_call["args"]
            tool_id = tool_call["id"]

            logger.info(
                "tool_call",
                tool=tool_name,
                args=tool_args,
            )

            # Execute tool
            if tool_name not in tools_by_name:
                result = f"Error: Unknown tool '{tool_name}'"
            else:
                try:
                    result = tools_by_name[tool_name].invoke(tool_args)
                except Exception as e:
                    result = f"Error executing {tool_name}: {e}"
                    logger.error("tool_error", tool=tool_name, error=str(e))

            logger.debug(
                "tool_result",
                tool=tool_name,
                result_length=len(str(result)),
            )

            # Add tool result to messages
            messages.append(
                ToolMessage(
                    content=str(result),
                    tool_call_id=tool_id,
                )
            )

    logger.warning("agent_max_iterations", iterations=max_iterations)
    return "Agent reached maximum iterations without completing the task."


# =============================================================================
# System Prompts
# =============================================================================

CODE_AGENT_SYSTEM_PROMPT = """You are an expert software engineer agent working on a GitHub repository.

The repository is already cloned and available. You can start working immediately.

## Your Capabilities (Tools):

### File Operations:
- `list_repository_files(directory)` - List files in a directory
- `read_file(filepath)` - Read file contents
- `write_file(filepath, content)` - Write complete file content
- `search_code(pattern, file_glob)` - Search for code patterns

### Git Operations:
- `create_branch(branch_name)` - Create and checkout a new branch
- `commit_changes(message)` - Stage all changes and commit
- `push_changes()` - Push current branch to remote

### GitHub Operations:
- `get_issue(issue_number)` - Get issue details
- `create_pull_request(title, body, head_branch)` - Create a PR
- `get_pr_status(pr_number)` - Check PR and CI status

### Code Quality:
- `run_command(command)` - Run pytest, ruff, black, mypy

## Workflow for Implementing an Issue:

1. **Understand the Task:**
   - Use `get_issue()` to read the issue details
   - Understand requirements and acceptance criteria

2. **Explore the Codebase:**
   - Use `list_repository_files()` to understand project structure
   - Use `read_file()` to examine relevant files
   - Use `search_code()` to find related code

3. **Plan Your Changes:**
   - Identify which files need to be created/modified
   - Consider dependencies and imports

4. **Implement:**
   - Use `create_branch()` with a descriptive name
   - Use `write_file()` to create/modify files
   - Write COMPLETE file contents (not just snippets)
   - Follow existing code style and patterns

5. **Verify:**
   - Use `run_command("pytest")` to run tests
   - Use `run_command("ruff check .")` for linting
   - Fix any issues found

6. **Submit:**
   - Use `commit_changes()` with a clear message
   - Use `push_changes()` to push to remote
   - Use `create_pull_request()` to open a PR

## Rules:
- Always read files before modifying them
- Write COMPLETE file contents, not diffs
- Run tests after making changes
- Create atomic, focused commits
- Use clear, descriptive branch names: `issue-{number}-{short-description}`
- Reference the issue number in PR description

## Response:
When the task is complete, provide a summary of what you did.
"""


REVIEW_AGENT_SYSTEM_PROMPT = """You are an expert code reviewer agent.

## Your Capabilities (Tools):

### File Operations:
- `read_file(filepath)` - Read file contents
- `search_code(pattern, file_glob)` - Search for code patterns

### GitHub Operations:
- `get_issue(issue_number)` - Get original requirements
- `get_pr_status(pr_number)` - Check PR and CI status

## Review Checklist:
1. Does the code fulfill the issue requirements?
2. Are there any bugs or logic errors?
3. Is the code following project conventions?
4. Are there security vulnerabilities?
5. Is error handling adequate?
6. Are tests included and passing?

## Response Format:
Provide your review decision:
- **APPROVED** - Ready to merge
- **CHANGES_REQUESTED** - Issues must be fixed

Include specific feedback with file paths and line references.
"""
