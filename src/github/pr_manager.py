"""Pull Request management."""

import re
from dataclasses import dataclass
from typing import Any

import structlog
from github.PullRequest import PullRequest

from src.github.client import CICheckResult, GitHubClient

logger = structlog.get_logger()


@dataclass
class PRInfo:
    """Information about a Pull Request."""

    number: int
    title: str
    body: str
    state: str
    head_branch: str
    base_branch: str
    mergeable: bool | None
    url: str
    diff: str
    files: list[dict[str, Any]]
    ci_status: list[CICheckResult]

    @property
    def ci_passed(self) -> bool:
        """Check if all CI checks passed."""
        if not self.ci_status:
            return True  # No checks = passed
        return all(
            check.conclusion == "success"
            for check in self.ci_status
            if check.status == "completed"
        )

    @property
    def ci_completed(self) -> bool:
        """Check if all CI checks are completed."""
        if not self.ci_status:
            return True
        return all(check.status == "completed" for check in self.ci_status)

    @property
    def failed_checks(self) -> list[CICheckResult]:
        """Get list of failed CI checks."""
        return [
            check
            for check in self.ci_status
            if check.status == "completed" and check.conclusion != "success"
        ]


class PRManager:
    """Manager for Pull Request operations."""

    def __init__(self, github_client: GitHubClient) -> None:
        self._client = github_client
        self._log = logger.bind(component="pr_manager")

    def create_pr(
        self,
        title: str,
        body: str,
        head_branch: str,
        base_branch: str = "main",
        issue_number: int | None = None,
    ) -> PRInfo:
        """
        Create a new Pull Request.

        Args:
            title: PR title
            body: PR description
            head_branch: Source branch
            base_branch: Target branch
            issue_number: Related issue number (for linking)

        Returns:
            PRInfo with created PR data
        """
        # Add issue reference to body
        if issue_number:
            body = f"{body}\n\nCloses #{issue_number}"

        pr = self._client.create_pull_request(
            title=title,
            body=body,
            head=head_branch,
            base=base_branch,
        )

        self._log.info(
            "pr_created",
            pr_number=pr.number,
            title=title,
            head=head_branch,
            base=base_branch,
            issue_number=issue_number,
        )

        return self.get_pr_info(pr.number)

    def get_pr_info(self, pr_number: int) -> PRInfo:
        """
        Get detailed information about a PR.

        Args:
            pr_number: PR number

        Returns:
            PRInfo with PR details
        """
        pr = self._client.get_pull_request(pr_number)
        diff = self._client.get_pr_diff(pr_number)
        files = self._client.get_pr_files(pr_number)
        ci_status = self._client.get_ci_status(pr_number)

        return PRInfo(
            number=pr.number,
            title=pr.title,
            body=pr.body or "",
            state=pr.state,
            head_branch=pr.head.ref,
            base_branch=pr.base.ref,
            mergeable=pr.mergeable,
            url=pr.html_url,
            diff=diff,
            files=files,
            ci_status=ci_status,
        )

    def add_review_comment(
        self,
        pr_number: int,
        body: str,
        event: str = "COMMENT",
    ) -> None:
        """
        Add a review comment to a PR.

        Args:
            pr_number: PR number
            body: Comment body
            event: Review event (COMMENT, APPROVE, REQUEST_CHANGES)
        """
        self._client.add_pr_review(pr_number, body, event)
        self._log.info("review_added", pr_number=pr_number, review_event=event)

    def add_comment(self, pr_number: int, body: str) -> None:
        """
        Add a simple comment to a PR.

        Args:
            pr_number: PR number
            body: Comment body
        """
        self._client.add_pr_comment(pr_number, body)
        self._log.debug("comment_added", pr_number=pr_number)

    def post_ci_summary(self, pr_number: int, pr_info: PRInfo) -> None:
        """
        Post a summary of CI results as a comment.

        Args:
            pr_number: PR number
            pr_info: PR information with CI status
        """
        if not pr_info.ci_status:
            return

        lines = ["## CI Status Summary", ""]

        for check in pr_info.ci_status:
            status_icon = self._get_status_icon(check.conclusion)
            lines.append(f"- {status_icon} **{check.name}**: {check.conclusion or check.status}")
            if check.output and check.output.get("summary"):
                summary = check.output["summary"][:200]
                lines.append(f"  > {summary}")

        if pr_info.ci_passed:
            lines.extend(["", "✅ All checks passed!"])
        else:
            lines.extend(["", "❌ Some checks failed. Please review and fix."])

        body = "\n".join(lines)
        self.add_comment(pr_number, body)

    def generate_pr_title(self, issue_title: str, task_type: str) -> str:
        """
        Generate a PR title from issue title.

        Args:
            issue_title: Original issue title
            task_type: Type of task

        Returns:
            Generated PR title
        """
        # Add prefix based on task type
        prefix_map = {
            "feature": "feat:",
            "bug_fix": "fix:",
            "refactor": "refactor:",
            "documentation": "docs:",
            "test": "test:",
        }

        prefix = prefix_map.get(task_type, "chore:")

        # Clean up issue title
        clean_title = issue_title.strip()
        clean_title = re.sub(r"^\[.*?\]\s*", "", clean_title)  # Remove tags
        clean_title = clean_title[0].lower() + clean_title[1:] if clean_title else clean_title

        return f"{prefix} {clean_title}"

    def generate_pr_body(
        self,
        issue_number: int,
        issue_title: str,
        changes_summary: str,
        files_changed: list[str],
    ) -> str:
        """
        Generate a PR body/description.

        Args:
            issue_number: Related issue number
            issue_title: Issue title
            changes_summary: Summary of changes made
            files_changed: List of files changed

        Returns:
            Generated PR body
        """
        lines = [
            f"## Summary",
            "",
            f"Resolves #{issue_number}: {issue_title}",
            "",
            "## Changes",
            "",
            changes_summary,
            "",
            "## Files Changed",
            "",
        ]

        for file in files_changed:
            lines.append(f"- `{file}`")

        lines.extend([
            "",
            "---",
            "",
            "🤖 *This PR was automatically generated by SDLC Agent*",
        ])

        return "\n".join(lines)

    def _get_status_icon(self, conclusion: str | None) -> str:
        """Get emoji icon for CI status."""
        icons = {
            "success": "✅",
            "failure": "❌",
            "cancelled": "⚪",
            "skipped": "⏭️",
            "timed_out": "⏱️",
            "neutral": "➖",
        }
        return icons.get(conclusion or "", "🔄")
