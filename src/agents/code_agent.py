"""Code Agent - generates code based on GitHub issues."""

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import structlog
from git import Repo

from src.core.config import Settings
from src.core.exceptions import CodeGenerationError, GitOperationError
from src.core.state_machine import IssueContext, IssueState, IssueStateMachine
from src.github.client import GitHubClient
from src.github.issue_parser import IssueParser, ParsedIssue
from src.github.pr_manager import PRManager
from src.llm.gateway import LLMGateway
from src.prompts.templates import (
    CODE_GENERATION_SYSTEM,
    FIX_ITERATION_SYSTEM,
    format_code_generation_prompt,
    format_fix_prompt,
)

logger = structlog.get_logger()


@dataclass
class GeneratedFile:
    """Represents a generated or modified file."""

    path: str
    content: str
    is_new: bool = True


@dataclass
class CodeGenerationResult:
    """Result of code generation."""

    files: list[GeneratedFile]
    summary: str
    raw_response: str


class CodeAgent:
    """
    Agent responsible for analyzing issues and generating code.

    This agent:
    1. Reads and parses GitHub issues
    2. Analyzes requirements
    3. Generates code changes
    4. Creates commits and pull requests
    5. Handles fix iterations based on review feedback
    """

    def __init__(
        self,
        settings: Settings,
        github_client: GitHubClient,
        llm_gateway: LLMGateway,
    ) -> None:
        self._settings = settings
        self._github = github_client
        self._llm = llm_gateway
        self._issue_parser = IssueParser()
        self._pr_manager = PRManager(github_client)
        self._log = logger.bind(component="code_agent")

    def process_issue(self, issue_number: int) -> dict[str, Any]:
        """
        Process a GitHub issue end-to-end.

        Args:
            issue_number: GitHub issue number to process

        Returns:
            Dict with processing results
        """
        self._log.info("processing_issue", issue_number=issue_number)

        # Get and parse issue
        issue = self._github.get_issue(issue_number)
        parsed_issue = self._issue_parser.parse(issue)

        # Initialize state machine
        context = IssueContext(
            issue_number=issue_number,
            issue_title=parsed_issue.title,
            issue_body=parsed_issue.body,
        )
        state_machine = IssueStateMachine(
            context,
            max_iterations=self._settings.max_iterations,
        )

        # Start processing
        state_machine.transition_to(IssueState.ANALYZING)

        try:
            # Build context
            state_machine.transition_to(IssueState.CONTEXT_BUILDING)
            repo_structure = self._get_repository_structure()
            relevant_files = self._get_relevant_files(parsed_issue)

            # Generate code
            state_machine.transition_to(IssueState.GENERATING_CODE)
            generation_result = self._generate_code(
                parsed_issue,
                repo_structure,
                relevant_files,
            )

            # Create branch and commit
            state_machine.transition_to(IssueState.COMMITTING)
            branch_name = self._create_branch_name(issue_number, parsed_issue.title)
            context.branch_name = branch_name

            self._apply_changes(generation_result, branch_name)

            # Create PR
            state_machine.transition_to(IssueState.CREATING_PR)
            pr_info = self._create_pull_request(
                parsed_issue,
                generation_result,
                branch_name,
            )
            context.pr_number = pr_info.number

            state_machine.transition_to(IssueState.CI_RUNNING)

            return {
                "success": True,
                "issue_number": issue_number,
                "pr_number": pr_info.number,
                "pr_url": pr_info.url,
                "branch": branch_name,
                "files_changed": [f.path for f in generation_result.files],
                "state": state_machine.state.value,
            }

        except Exception as e:
            self._log.error(
                "issue_processing_failed",
                issue_number=issue_number,
                error=str(e),
            )
            state_machine.transition_to(IssueState.FAILED)
            raise

    def fix_based_on_review(
        self,
        issue_number: int,
        pr_number: int,
        review_feedback: str,
        iteration: int,
    ) -> dict[str, Any]:
        """
        Fix code based on review feedback.

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

        # Get original issue
        issue = self._github.get_issue(issue_number)
        parsed_issue = self._issue_parser.parse(issue)

        # Get current PR info
        pr_info = self._pr_manager.get_pr_info(pr_number)

        # Generate fixes
        fix_result = self._generate_fixes(
            parsed_issue,
            pr_info.diff,
            review_feedback,
            iteration,
        )

        # Apply fixes to the existing branch
        self._apply_changes(fix_result, pr_info.head_branch, amend=False)

        return {
            "success": True,
            "iteration": iteration,
            "files_changed": [f.path for f in fix_result.files],
            "summary": fix_result.summary,
        }

    def _get_repository_structure(self, max_depth: int = 3) -> str:
        """Get repository file structure as a string."""
        try:
            structure = self._github.get_repository_structure()
            lines = []
            self._format_structure(structure, lines, "", max_depth, 0)
            return "\n".join(lines) or "Empty repository"
        except Exception as e:
            self._log.warning("failed_to_get_repo_structure", error=str(e))
            return "Unable to retrieve repository structure"

    def _format_structure(
        self,
        items: list[dict],
        lines: list[str],
        prefix: str,
        max_depth: int,
        current_depth: int,
    ) -> None:
        """Recursively format repository structure."""
        if current_depth >= max_depth:
            return

        for item in items:
            icon = "📁" if item["type"] == "dir" else "📄"
            lines.append(f"{prefix}{icon} {item['name']}")

            if item["type"] == "dir" and current_depth < max_depth - 1:
                try:
                    subitems = self._github.get_repository_structure(item["path"])
                    self._format_structure(
                        subitems, lines, prefix + "  ", max_depth, current_depth + 1
                    )
                except Exception:
                    pass

    def _get_relevant_files(self, parsed_issue: ParsedIssue) -> dict[str, str]:
        """Get content of files relevant to the issue."""
        relevant_files: dict[str, str] = {}

        # Get explicitly mentioned files
        for filepath in parsed_issue.mentioned_files:
            content = self._github.get_file_content(filepath)
            if content:
                relevant_files[filepath] = content

        # TODO: Add smart file discovery based on task type
        # For now, we rely on mentioned files and LLM context

        return relevant_files

    def _generate_code(
        self,
        parsed_issue: ParsedIssue,
        repo_structure: str,
        existing_files: dict[str, str],
    ) -> CodeGenerationResult:
        """Generate code using LLM."""
        prompt = format_code_generation_prompt(
            issue_description=parsed_issue.full_description,
            repository_structure=repo_structure,
            existing_files=existing_files,
        )

        response = self._llm.generate(
            prompt=prompt,
            system_prompt=CODE_GENERATION_SYSTEM,
            temperature=0.3,
            max_tokens=self._settings.openai_max_tokens,
        )

        files = self._parse_generated_files(response.content)
        summary = self._extract_summary(response.content)

        if not files:
            raise CodeGenerationError(
                "No files were generated from LLM response",
                details={"response_preview": response.content[:500]},
            )

        self._log.info(
            "code_generated",
            files_count=len(files),
            total_tokens=response.total_tokens,
        )

        return CodeGenerationResult(
            files=files,
            summary=summary,
            raw_response=response.content,
        )

    def _generate_fixes(
        self,
        parsed_issue: ParsedIssue,
        previous_diff: str,
        review_feedback: str,
        iteration: int,
    ) -> CodeGenerationResult:
        """Generate fixes based on review feedback."""
        prompt = format_fix_prompt(
            issue_description=parsed_issue.full_description,
            previous_implementation=previous_diff,
            review_feedback=review_feedback,
            iteration=iteration,
        )

        response = self._llm.generate(
            prompt=prompt,
            system_prompt=FIX_ITERATION_SYSTEM,
            temperature=0.3,
        )

        files = self._parse_generated_files(response.content)
        summary = f"Fix iteration {iteration}: Addressed review feedback"

        return CodeGenerationResult(
            files=files,
            summary=summary,
            raw_response=response.content,
        )

    def _parse_generated_files(self, content: str) -> list[GeneratedFile]:
        """Parse generated files from LLM response."""
        files = []

        # Pattern to match file blocks
        file_pattern = r"###\s*FILE:\s*([^\n]+)\n```(?:\w+)?\n(.*?)```"
        matches = re.findall(file_pattern, content, re.DOTALL)

        for filepath, code in matches:
            filepath = filepath.strip()
            code = code.strip()

            # Check if file exists in repo
            existing = self._github.get_file_content(filepath)
            is_new = existing is None

            files.append(GeneratedFile(
                path=filepath,
                content=code,
                is_new=is_new,
            ))

        return files

    def _extract_summary(self, content: str) -> str:
        """Extract summary from LLM response."""
        # Try to find a summary section
        summary_pattern = r"(?:##\s*)?Summary[:\s]*\n(.*?)(?=\n##|\n###|```|$)"
        match = re.search(summary_pattern, content, re.IGNORECASE | re.DOTALL)

        if match:
            return match.group(1).strip()

        # Default summary
        return "Code changes generated by SDLC Agent"

    def _create_branch_name(self, issue_number: int, title: str) -> str:
        """Create a branch name from issue number and title."""
        # Sanitize title
        safe_title = re.sub(r"[^a-zA-Z0-9\s-]", "", title.lower())
        safe_title = re.sub(r"\s+", "-", safe_title)
        safe_title = safe_title[:40]  # Limit length

        return f"issue-{issue_number}-{safe_title}"

    def _apply_changes(
        self,
        result: CodeGenerationResult,
        branch_name: str,
        amend: bool = False,
    ) -> None:
        """Apply generated changes to a git branch."""
        workspace = self._settings.workspace_dir
        workspace.mkdir(parents=True, exist_ok=True)

        repo_path = workspace / self._settings.repo_name

        try:
            # Clone or update repo
            if repo_path.exists():
                repo = Repo(repo_path)
                repo.remotes.origin.fetch()
            else:
                repo = Repo.clone_from(
                    f"https://x-access-token:{self._settings.github_token}@github.com/{self._settings.github_repository}.git",
                    repo_path,
                )

            # Create or checkout branch
            if branch_name in [ref.name for ref in repo.references]:
                repo.git.checkout(branch_name)
            else:
                repo.git.checkout("-b", branch_name)

            # Apply file changes
            for file in result.files:
                file_path = repo_path / file.path
                file_path.parent.mkdir(parents=True, exist_ok=True)
                file_path.write_text(file.content)
                repo.index.add([file.path])

            # Commit
            commit_message = f"feat: {result.summary}\n\nGenerated by SDLC Agent"
            if amend:
                repo.git.commit("--amend", "-m", commit_message)
            else:
                repo.index.commit(commit_message)

            # Push
            repo.git.push("--set-upstream", "origin", branch_name, "--force")

            self._log.info(
                "changes_applied",
                branch=branch_name,
                files_count=len(result.files),
            )

        except Exception as e:
            raise GitOperationError(
                f"Failed to apply changes: {e}",
                details={"branch": branch_name, "error": str(e)},
            ) from e

    def _create_pull_request(
        self,
        parsed_issue: ParsedIssue,
        result: CodeGenerationResult,
        branch_name: str,
    ) -> Any:
        """Create a pull request for the changes."""
        title = self._pr_manager.generate_pr_title(
            parsed_issue.title,
            parsed_issue.task_type.value,
        )

        body = self._pr_manager.generate_pr_body(
            issue_number=parsed_issue.number,
            issue_title=parsed_issue.title,
            changes_summary=result.summary,
            files_changed=[f.path for f in result.files],
        )

        return self._pr_manager.create_pr(
            title=title,
            body=body,
            head_branch=branch_name,
            issue_number=parsed_issue.number,
        )
