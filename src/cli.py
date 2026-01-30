"""CLI interface for SDLC Agent System."""

import atexit
import sys
from typing import Any

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from src.agents.code_agent import CodeAgent
from src.agents.reviewer_agent import ReviewerAgent
from src.core.config import Settings, get_settings
from src.core.exceptions import SDLCAgentError
from src.core.logging import setup_logging
from src.github.client import GitHubClient
from src.llm.gateway import LLMGateway, flush_langfuse

# Register Langfuse flush on exit
atexit.register(flush_langfuse)

console = Console()


def create_agents(settings: Settings) -> tuple[CodeAgent, ReviewerAgent]:
    """Create agent instances with shared dependencies."""
    github_client = GitHubClient(
        token=settings.github_token,
        repository=settings.github_repository,
    )

    # CodeAgent uses LangChain with tool calling
    code_agent = CodeAgent(settings, github_client)

    # ReviewerAgent still uses LLMGateway (for now)
    llm_gateway = LLMGateway(settings)
    reviewer_agent = ReviewerAgent(settings, github_client, llm_gateway)

    return code_agent, reviewer_agent


@click.group()
@click.option(
    "--log-level",
    default="INFO",
    type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR"]),
    help="Logging level",
)
@click.option(
    "--log-format",
    default="text",
    type=click.Choice(["text", "json"]),
    help="Log output format",
)
@click.pass_context
def main(ctx: click.Context, log_level: str, log_format: str) -> None:
    """SDLC Agent - Automated GitHub Development Pipeline."""
    setup_logging(level=log_level, log_format=log_format)
    ctx.ensure_object(dict)
    ctx.obj["log_level"] = log_level


@main.command()
@click.argument("issue_number", type=int)
@click.option(
    "--max-steps",
    default=15,
    type=int,
    help="Maximum agent steps (default: 15)",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Analyze issue without making changes",
)
@click.pass_context
def process(ctx: click.Context, issue_number: int, max_steps: int, dry_run: bool) -> None:
    """Process a GitHub issue and create a Pull Request."""
    console.print(
        Panel(
            f"Processing Issue #{issue_number}",
            title="🚀 SDLC Agent",
            border_style="blue",
        )
    )

    try:
        settings = get_settings()
        code_agent, _ = create_agents(settings)

        if dry_run:
            console.print("[yellow]Dry run mode - no changes will be made[/yellow]")
            # TODO: Implement dry run analysis
            console.print("Dry run analysis not yet implemented")
            return

        with console.status("[bold green]Processing issue..."):
            result = code_agent.process_issue(issue_number, max_iterations=max_steps)

        # Display results
        if result["success"]:
            console.print("\n[bold green]✅ Issue processed successfully![/bold green]\n")

            table = Table(show_header=False, box=None)
            table.add_row("Issue:", f"#{result['issue_number']}")
            if result.get("branch"):
                table.add_row("Branch:", result["branch"])
            console.print(table)

            if result.get("summary"):
                console.print(f"\n[bold]Summary:[/bold] {result['summary']}")

            console.print("\n[dim]Check GitHub for PR status.[/dim]")
        else:
            console.print("[bold red]❌ Failed to process issue[/bold red]")
            if result.get("summary"):
                console.print(f"[dim]{result['summary']}[/dim]")
            sys.exit(1)

    except SDLCAgentError as e:
        console.print(f"[bold red]Error:[/bold red] {e.message}")
        if e.details:
            console.print(f"[dim]Details: {e.details}[/dim]")
        sys.exit(1)
    except Exception as e:
        console.print(f"[bold red]Unexpected error:[/bold red] {e}")
        raise


@main.command()
@click.argument("pr_number", type=int)
@click.option(
    "--issue",
    type=int,
    help="Related issue number for requirements checking",
)
@click.pass_context
def review(ctx: click.Context, pr_number: int, issue: int | None) -> None:
    """Review a Pull Request."""
    console.print(
        Panel(
            f"Reviewing PR #{pr_number}",
            title="🔍 AI Reviewer",
            border_style="cyan",
        )
    )

    try:
        settings = get_settings()
        _, reviewer_agent = create_agents(settings)

        with console.status("[bold cyan]Analyzing PR..."):
            result = reviewer_agent.review_pr(pr_number, issue)

        # Display results
        decision_color = {
            "APPROVED": "green",
            "CHANGES_REQUESTED": "yellow",
            "COMMENT": "blue",
        }.get(result.decision.value, "white")

        console.print(f"\n[bold {decision_color}]Decision: {result.decision.value}[/bold {decision_color}]")
        console.print(f"\n[bold]Summary:[/bold]\n{result.summary}")

        if result.issues:
            console.print("\n[bold]Issues Found:[/bold]")
            for issue_item in result.issues:
                severity_color = {
                    "CRITICAL": "red",
                    "MAJOR": "yellow",
                    "MINOR": "blue",
                }.get(issue_item.severity, "white")
                console.print(
                    f"  [{severity_color}][{issue_item.severity}][/{severity_color}] {issue_item.description}"
                )

        if result.positive_aspects:
            console.print("\n[bold green]Positive Aspects:[/bold green]")
            for aspect in result.positive_aspects:
                console.print(f"  ✨ {aspect}")

        console.print("\n[dim]Review has been posted to the PR.[/dim]")

    except SDLCAgentError as e:
        console.print(f"[bold red]Error:[/bold red] {e.message}")
        sys.exit(1)


@main.command()
@click.argument("pr_number", type=int)
@click.option(
    "--issue",
    type=int,
    help="Related issue number",
)
@click.pass_context
def check(ctx: click.Context, pr_number: int, issue: int | None) -> None:
    """Check PR status and get recommended action."""
    console.print(
        Panel(
            f"Checking PR #{pr_number}",
            title="📋 Status Check",
            border_style="magenta",
        )
    )

    try:
        settings = get_settings()
        _, reviewer_agent = create_agents(settings)

        with console.status("[bold magenta]Checking PR status..."):
            result = reviewer_agent.check_and_decide(pr_number, issue)

        action = result["action"]
        action_colors = {
            "wait": "yellow",
            "fix_ci": "red",
            "request_fixes": "orange3",
            "merge": "green",
        }

        console.print(f"\n[bold {action_colors.get(action, 'white')}]Recommended Action: {action.upper()}[/bold {action_colors.get(action, 'white')}]")
        console.print(f"Reason: {result['reason']}")

        if action == "fix_ci" and "failed_checks" in result:
            console.print("\n[bold]Failed Checks:[/bold]")
            for check_info in result["failed_checks"]:
                console.print(f"  ❌ {check_info['name']}: {check_info['conclusion']}")

        if action == "request_fixes" and "issues" in result:
            console.print("\n[bold]Issues to Fix:[/bold]")
            for issue_info in result["issues"]:
                console.print(f"  • [{issue_info['severity']}] {issue_info['description']}")

    except SDLCAgentError as e:
        console.print(f"[bold red]Error:[/bold red] {e.message}")
        sys.exit(1)


@main.command()
@click.argument("issue_number", type=int)
@click.option(
    "--max-steps",
    default=15,
    type=int,
    help="Maximum agent steps per iteration (default: 15)",
)
@click.option(
    "--max-iterations",
    default=5,
    type=int,
    help="Maximum fix iterations",
)
@click.option(
    "--wait-ci",
    default=30,
    type=int,
    help="Seconds to wait for CI between iterations",
)
@click.pass_context
def run_cycle(
    ctx: click.Context,
    issue_number: int,
    max_steps: int,
    max_iterations: int,
    wait_ci: int,
) -> None:
    """Run full SDLC cycle: Issue → PR → Review → Auto-fix loop.

    The agent maintains state between iterations - it remembers
    what it did and just receives new feedback each time.
    """
    import time

    console.print(
        Panel(
            f"Running Full Cycle for Issue #{issue_number}",
            title="🔄 SDLC Cycle",
            border_style="magenta",
        )
    )

    try:
        settings = get_settings()
        code_agent, reviewer_agent = create_agents(settings)

        # Step 1: Process issue and create PR
        console.print("\n[bold]═══ Step 1: Process Issue & Create PR ═══[/bold]")

        result = code_agent.process_issue(issue_number, max_iterations=max_steps)

        if not result["success"]:
            console.print("[bold red]❌ Failed to process issue[/bold red]")
            if result.get("summary"):
                console.print(f"[dim]{result['summary']}[/dim]")
            sys.exit(1)

        pr_number = result.get("pr_number")
        pr_url = result.get("pr_url")
        branch = result.get("branch")

        if pr_url:
            console.print(f"[green]✅ PR created: {pr_url}[/green]")
        elif branch:
            console.print(f"[yellow]Changes on branch: {branch}[/yellow]")

        # If no PR was created, ask agent to create one
        if not pr_number:
            console.print("[yellow]⚠️ No PR created. Asking agent to create PR...[/yellow]")
            fix_result = code_agent.continue_with_feedback(
                feedback="You forgot to create a Pull Request! Please create a PR now with create_pull_request() and then call finish().",
                max_iterations=5,
            )
            pr_number = fix_result.get("pr_number") or code_agent.state.pr_number
            pr_url = code_agent.state.pr_url if code_agent.state else None

            if pr_url:
                console.print(f"[green]✅ PR created: {pr_url}[/green]")

        if not pr_number:
            console.print("[bold red]❌ Could not create PR. Exiting.[/bold red]")
            sys.exit(1)

        # Step 2: Review and fix loop
        console.print("\n[bold]═══ Step 2: Review & Fix Loop ═══[/bold]")

        iteration = 0
        while iteration < max_iterations:
            iteration += 1
            console.print(f"\n[bold cyan]── Review Iteration {iteration}/{max_iterations} ──[/bold cyan]")

            # Wait for CI
            console.print(f"[dim]Waiting {wait_ci}s for CI...[/dim]")
            time.sleep(wait_ci)

            # Check and review
            with console.status("[bold]Reviewing PR..."):
                decision = reviewer_agent.check_and_decide(pr_number, issue_number)

            # Display decision details
            _display_review_decision(decision)

            if decision["action"] == "merge":
                console.print("\n[bold green]✅ PR is ready to merge![/bold green]")
                console.print(f"[dim]Merge it: gh pr merge {pr_number} --squash[/dim]")
                break

            elif decision["action"] == "wait":
                console.print("[yellow]⏳ CI still running, will check again...[/yellow]")
                continue

            elif decision["action"] in ("fix_ci", "request_fixes"):
                # Build feedback message for the agent
                feedback = _build_feedback_message(decision)

                console.print("\n[yellow]🔧 Applying fixes...[/yellow]")
                console.print("[dim]Agent continues with full context from previous work[/dim]")

                fix_result = code_agent.continue_with_feedback(
                    feedback=feedback,
                    max_iterations=max_steps,
                )

                if fix_result.get("success"):
                    console.print("[green]✅ Fixes applied and pushed[/green]")
                else:
                    console.print("[yellow]⚠️ Fix attempt incomplete[/yellow]")

                if fix_result.get("summary"):
                    console.print(f"[dim]{fix_result['summary']}[/dim]")
        else:
            console.print(
                f"\n[bold red]⚠️ Max iterations ({max_iterations}) reached[/bold red]"
            )
            console.print("Manual review may be needed.")

    except SDLCAgentError as e:
        console.print(f"[bold red]Error:[/bold red] {e.message}")
        sys.exit(1)


def _display_review_decision(decision: dict) -> None:
    """Display review decision details."""
    console.print(f"\n[bold]Decision:[/bold] {decision['action']}")
    console.print(f"[bold]Reason:[/bold] {decision['reason']}")

    # Show CI status if available
    if "ci_status" in decision:
        console.print("\n[bold]CI Status:[/bold]")
        for check in decision["ci_status"]:
            console.print(f"  - {check['name']}: {check['status']}")

    # Show failed checks details
    if "failed_checks" in decision:
        console.print("\n[bold red]Failed CI Checks:[/bold red]")
        for check in decision["failed_checks"]:
            console.print(f"  - [red]{check['name']}[/red]: {check.get('conclusion', 'failed')}")
            if check.get("output"):
                output = check["output"]
                if isinstance(output, dict):
                    if output.get("summary"):
                        console.print(f"    [dim]{output['summary'][:500]}[/dim]")
                    if output.get("annotations"):
                        console.print("    [yellow]Errors:[/yellow]")
                        for ann in output["annotations"][:5]:
                            console.print(f"      [red]{ann['path']}:{ann['line']}[/red]: {ann['message']}")
                elif isinstance(output, str):
                    console.print(f"    [dim]{output[:500]}[/dim]")

    # Show review issues
    if "issues" in decision:
        console.print("\n[bold]Review Issues:[/bold]")
        for issue in decision["issues"]:
            severity = issue.get("severity", "info")
            color = "red" if severity == "CRITICAL" else "yellow" if severity == "MAJOR" else "dim"
            console.print(f"  - [{color}][{severity}][/{color}] {issue['description']}")
            if issue.get("file"):
                console.print(f"    [dim]File: {issue['file']}:{issue.get('line', '')}[/dim]")
            if issue.get("suggestion"):
                console.print(f"    [green]Suggestion: {issue['suggestion']}[/green]")

    # Show review summary
    if decision.get("review_summary"):
        console.print(f"\n[bold]Review Summary:[/bold]\n{decision['review_summary']}")


def _build_feedback_message(decision: dict) -> str:
    """Build feedback message for agent from review decision."""
    parts = ["CI/Review feedback - please fix the issues and push again:\n"]

    # Add failed CI checks info
    if "failed_checks" in decision:
        parts.append("FAILED CI CHECKS:")
        for check in decision["failed_checks"]:
            parts.append(f"- {check['name']}: {check.get('conclusion', 'failed')}")
            if check.get("output"):
                output = check["output"]
                if isinstance(output, dict):
                    if output.get("summary"):
                        parts.append(f"  Error: {output['summary']}")
                    if output.get("text"):
                        parts.append(f"  Details: {output['text'][:1000]}")
                    # Add annotations with file:line info
                    if output.get("annotations"):
                        parts.append("  Errors at:")
                        for ann in output["annotations"]:
                            parts.append(f"    - {ann['path']}:{ann['line']}: {ann['message']}")
                elif isinstance(output, str):
                    parts.append(f"  Error: {output}")
        parts.append("")

    # Add review summary
    if decision.get("review_summary"):
        parts.append(f"REVIEW SUMMARY:\n{decision['review_summary']}\n")

    # Add issues
    if "issues" in decision:
        parts.append("ISSUES TO FIX:")
        for i in decision["issues"]:
            line = f"- [{i['severity']}] {i['description']}"
            if i.get("file"):
                line += f" (file: {i['file']}:{i.get('line', '')})"
            if i.get("suggestion"):
                line += f"\n  Suggestion: {i['suggestion']}"
            parts.append(line)
        parts.append("")

    # Add hint to use get_ci_logs if CI failed
    if "failed_checks" in decision:
        parts.append("TIP: Use get_ci_logs(pr_number) to see detailed error output from failed tests.")
        parts.append("")

    parts.append("Fix the issues, commit, push, then call finish().")

    return "\n".join(parts)


@main.command()
@click.argument("title")
@click.option(
    "--body", "-b",
    default="",
    help="Issue body/description",
)
@click.option(
    "--requirements", "-r",
    multiple=True,
    help="Requirements (can be used multiple times)",
)
@click.option(
    "--files", "-f",
    multiple=True,
    help="Files to modify (can be used multiple times)",
)
@click.option(
    "--auto-process",
    is_flag=True,
    help="Automatically process the issue after creation",
)
@click.pass_context
def create_issue(
    ctx: click.Context,
    title: str,
    body: str,
    requirements: tuple[str, ...],
    files: tuple[str, ...],
    auto_process: bool,
) -> None:
    """Create a new GitHub issue and optionally process it."""
    console.print(
        Panel(
            f"Creating Issue: {title}",
            title="📝 New Issue",
            border_style="green",
        )
    )

    try:
        settings = get_settings()
        github_client = GitHubClient(
            token=settings.github_token,
            repository=settings.github_repository,
        )

        # Build issue body
        issue_body_parts = []
        if body:
            issue_body_parts.append("## Description\n" + body)

        if requirements:
            issue_body_parts.append("\n## Requirements")
            for req in requirements:
                issue_body_parts.append(f"- {req}")

        if files:
            issue_body_parts.append("\n## Files to modify")
            for f in files:
                issue_body_parts.append(f"- `{f}`")

        full_body = "\n".join(issue_body_parts)

        # Create issue via GitHub API
        with console.status("[bold green]Creating issue..."):
            issue = github_client.repo.create_issue(
                title=title,
                body=full_body,
                labels=["agent"] if auto_process else [],
            )

        console.print(f"\n[bold green]✅ Issue created![/bold green]")
        console.print(f"Issue #: {issue.number}")
        console.print(f"URL: {issue.html_url}")

        if auto_process:
            console.print("\n[yellow]Auto-processing enabled, starting Code Agent...[/yellow]")
            ctx.invoke(process, issue_number=issue.number)
        else:
            console.print(f"\n[dim]To process: sdlc-agent process {issue.number}[/dim]")

    except SDLCAgentError as e:
        console.print(f"[bold red]Error:[/bold red] {e.message}")
        sys.exit(1)


@main.command()
@click.option(
    "--state",
    type=click.Choice(["open", "closed", "all"]),
    default="open",
    help="Filter by issue state",
)
@click.option(
    "--label",
    default=None,
    help="Filter by label",
)
@click.option(
    "--limit",
    default=10,
    type=int,
    help="Maximum number of issues to show",
)
@click.pass_context
def list_issues(
    ctx: click.Context,
    state: str,
    label: str | None,
    limit: int,
) -> None:
    """List GitHub issues in the repository."""
    try:
        settings = get_settings()
        github_client = GitHubClient(
            token=settings.github_token,
            repository=settings.github_repository,
        )

        with console.status("[bold]Fetching issues..."):
            issues = github_client.repo.get_issues(
                state=state,
                labels=[label] if label else [],
            )

        table = Table(title=f"Issues ({state})")
        table.add_column("#", style="cyan", width=6)
        table.add_column("Title", style="white")
        table.add_column("Labels", style="yellow")
        table.add_column("State", style="green")

        count = 0
        for issue in issues:
            if count >= limit:
                break
            # Skip pull requests (they also appear in issues API)
            if issue.pull_request:
                continue

            labels_str = ", ".join([l.name for l in issue.labels])
            table.add_row(
                str(issue.number),
                issue.title[:50] + "..." if len(issue.title) > 50 else issue.title,
                labels_str or "-",
                issue.state,
            )
            count += 1

        console.print(table)

        if count == 0:
            console.print("[dim]No issues found.[/dim]")

    except SDLCAgentError as e:
        console.print(f"[bold red]Error:[/bold red] {e.message}")
        sys.exit(1)


@main.command()
@click.option(
    "--state",
    type=click.Choice(["open", "closed", "all"]),
    default="open",
    help="Filter by PR state",
)
@click.option(
    "--limit",
    default=10,
    type=int,
    help="Maximum number of PRs to show",
)
@click.pass_context
def list_prs(ctx: click.Context, state: str, limit: int) -> None:
    """List Pull Requests in the repository."""
    try:
        settings = get_settings()
        github_client = GitHubClient(
            token=settings.github_token,
            repository=settings.github_repository,
        )

        with console.status("[bold]Fetching pull requests..."):
            prs = github_client.repo.get_pulls(state=state)

        table = Table(title=f"Pull Requests ({state})")
        table.add_column("#", style="cyan", width=6)
        table.add_column("Title", style="white")
        table.add_column("Branch", style="blue")
        table.add_column("CI", style="yellow")
        table.add_column("State", style="green")

        count = 0
        for pr in prs:
            if count >= limit:
                break

            # Get CI status
            ci_status = "⏳"
            try:
                commit = github_client.repo.get_commit(pr.head.sha)
                checks = list(commit.get_check_runs())
                if checks:
                    all_passed = all(c.conclusion == "success" for c in checks if c.status == "completed")
                    any_failed = any(c.conclusion == "failure" for c in checks if c.status == "completed")
                    all_completed = all(c.status == "completed" for c in checks)

                    if all_completed and all_passed:
                        ci_status = "✅"
                    elif any_failed:
                        ci_status = "❌"
                    else:
                        ci_status = "🔄"
            except Exception:
                ci_status = "?"

            table.add_row(
                str(pr.number),
                pr.title[:40] + "..." if len(pr.title) > 40 else pr.title,
                pr.head.ref[:20],
                ci_status,
                pr.state,
            )
            count += 1

        console.print(table)

        if count == 0:
            console.print("[dim]No pull requests found.[/dim]")

    except SDLCAgentError as e:
        console.print(f"[bold red]Error:[/bold red] {e.message}")
        sys.exit(1)


@main.command()
@click.argument("issue_number", type=int)
@click.pass_context
def show_issue(ctx: click.Context, issue_number: int) -> None:
    """Show details of a specific issue."""
    try:
        settings = get_settings()
        github_client = GitHubClient(
            token=settings.github_token,
            repository=settings.github_repository,
        )

        from src.github.issue_parser import IssueParser

        with console.status("[bold]Fetching issue..."):
            issue = github_client.get_issue(issue_number)
            parser = IssueParser()
            parsed = parser.parse(issue)

        console.print(Panel(
            f"[bold]{parsed.title}[/bold]\n\n"
            f"[dim]#{parsed.number} • {parsed.task_type.value}[/dim]",
            title="Issue Details",
            border_style="cyan",
        ))

        console.print(f"\n[bold]Description:[/bold]\n{parsed.body[:500]}{'...' if len(parsed.body) > 500 else ''}")

        if parsed.requirements:
            console.print("\n[bold]Requirements:[/bold]")
            for req in parsed.requirements:
                console.print(f"  • {req}")

        if parsed.acceptance_criteria:
            console.print("\n[bold]Acceptance Criteria:[/bold]")
            for ac in parsed.acceptance_criteria:
                console.print(f"  ✓ {ac}")

        if parsed.mentioned_files:
            console.print("\n[bold]Referenced Files:[/bold]")
            for f in parsed.mentioned_files:
                console.print(f"  📄 {f}")

        if parsed.labels:
            console.print(f"\n[bold]Labels:[/bold] {', '.join(parsed.labels)}")

        console.print(f"\n[dim]URL: {issue.html_url}[/dim]")

    except SDLCAgentError as e:
        console.print(f"[bold red]Error:[/bold red] {e.message}")
        sys.exit(1)


@main.command()
def version() -> None:
    """Show version information."""
    from src import __version__

    console.print(f"SDLC Agent version {__version__}")


@main.command()
@click.pass_context
def config(ctx: click.Context) -> None:
    """Show current configuration."""
    try:
        settings = get_settings()

        table = Table(title="Current Configuration")
        table.add_column("Setting", style="cyan")
        table.add_column("Value", style="green")

        table.add_row("Repository", settings.github_repository)
        table.add_row("Model", settings.openai_model)
        table.add_row("Base URL", settings.openai_base_url or "api.openai.com")
        table.add_row("Max Iterations", str(settings.max_iterations))
        table.add_row("Log Level", settings.log_level)
        table.add_row("Workspace", str(settings.workspace_dir))

        # Langfuse observability
        if settings.langfuse_enabled:
            table.add_row("Langfuse", "✅ Enabled")
            table.add_row("Langfuse URL", settings.langfuse_base_url or "cloud.langfuse.com")
        else:
            table.add_row("Langfuse", "❌ Disabled")

        # Show masked tokens
        table.add_row(
            "GitHub Token",
            "***" + settings.github_token[-4:] if settings.github_token else "Not set",
        )

        console.print(table)

    except Exception as e:
        console.print(f"[bold red]Error loading config:[/bold red] {e}")
        console.print("\nMake sure you have a .env file or environment variables set.")
        console.print("See .env.example for required variables.")


@main.command()
@click.option(
    "--host",
    default="0.0.0.0",
    help="Host to bind to",
)
@click.option(
    "--port",
    default=8000,
    type=int,
    help="Port to listen on",
)
def web(host: str, port: int) -> None:
    """Start the web interface."""
    console.print(
        Panel(
            f"Starting web server on http://{host}:{port}",
            title="🌐 SDLC Agent Web",
            border_style="cyan",
        )
    )

    from src.web.app import start_server
    start_server(host=host, port=port)


if __name__ == "__main__":
    main()
