"""Reviewer Agent - performs AI code review on Pull Requests."""

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any

import structlog

from src.core.config import Settings
from src.github.client import GitHubClient
from src.github.pr_manager import PRInfo, PRManager
from src.llm.gateway import LLMGateway
from src.prompts.templates import CODE_REVIEW_SYSTEM, format_code_review_prompt

logger = structlog.get_logger()


class ReviewDecision(str, Enum):
    """Possible review decisions."""

    APPROVED = "APPROVED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    COMMENT = "COMMENT"


@dataclass
class ReviewIssue:
    """An issue found during code review."""

    severity: str  # CRITICAL, MAJOR, MINOR
    description: str
    file: str | None = None
    line: int | None = None
    suggestion: str | None = None


@dataclass
class ReviewResult:
    """Result of a code review."""

    decision: ReviewDecision
    summary: str
    issues: list[ReviewIssue]
    positive_aspects: list[str]
    recommendations: list[str]
    raw_review: str

    @property
    def has_critical_issues(self) -> bool:
        """Check if there are any critical issues."""
        return any(issue.severity == "CRITICAL" for issue in self.issues)

    @property
    def has_major_issues(self) -> bool:
        """Check if there are any major issues."""
        return any(issue.severity == "MAJOR" for issue in self.issues)

    def to_github_comment(self) -> str:
        """Format review as GitHub comment."""
        lines = [
            "# 🤖 AI Code Review",
            "",
            "## Summary",
            "",
            self.summary,
            "",
        ]

        # Status badge
        if self.decision == ReviewDecision.APPROVED:
            lines.append("**Status:** ✅ APPROVED")
        elif self.decision == ReviewDecision.CHANGES_REQUESTED:
            lines.append("**Status:** 🔄 CHANGES REQUESTED")
        else:
            lines.append("**Status:** 💬 COMMENT")
        lines.append("")

        # Issues
        if self.issues:
            lines.extend([
                "## Issues Found",
                "",
            ])
            for issue in self.issues:
                icon = {"CRITICAL": "🔴", "MAJOR": "🟠", "MINOR": "🟡"}.get(
                    issue.severity, "⚪"
                )
                lines.append(f"### {icon} [{issue.severity}] {issue.description}")
                if issue.file:
                    lines.append(f"- **File:** `{issue.file}`")
                if issue.line:
                    lines.append(f"- **Line:** {issue.line}")
                if issue.suggestion:
                    lines.append(f"- **Suggestion:** {issue.suggestion}")
                lines.append("")

        # Positive aspects
        if self.positive_aspects:
            lines.extend([
                "## ✨ Positive Aspects",
                "",
            ])
            for aspect in self.positive_aspects:
                lines.append(f"- {aspect}")
            lines.append("")

        # Recommendations
        if self.recommendations:
            lines.extend([
                "## 💡 Recommendations",
                "",
            ])
            for rec in self.recommendations:
                lines.append(f"- {rec}")
            lines.append("")

        lines.extend([
            "---",
            "*This review was generated automatically by SDLC Agent*",
        ])

        return "\n".join(lines)


class ReviewerAgent:
    """
    Agent responsible for reviewing Pull Requests.

    This agent:
    1. Analyzes PR changes
    2. Checks CI/CD results
    3. Compares implementation against requirements
    4. Generates detailed review feedback
    5. Posts review to GitHub
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
        self._pr_manager = PRManager(github_client)
        self._log = logger.bind(component="reviewer_agent")

    def review_pr(
        self,
        pr_number: int,
        issue_number: int | None = None,
    ) -> ReviewResult:
        """
        Review a Pull Request.

        Args:
            pr_number: PR number to review
            issue_number: Related issue number (for requirements check)

        Returns:
            ReviewResult with review details
        """
        self._log.info("reviewing_pr", pr_number=pr_number, issue_number=issue_number)

        # Get PR info
        pr_info = self._pr_manager.get_pr_info(pr_number)

        # Get issue description if provided
        issue_description = ""
        if issue_number:
            issue = self._github.get_issue(issue_number)
            issue_description = f"# Issue #{issue_number}: {issue.title}\n\n{issue.body or ''}"

        # Format CI results
        ci_results = self._format_ci_results(pr_info)

        # Generate review
        review_result = self._generate_review(
            pr_info=pr_info,
            issue_description=issue_description,
            ci_results=ci_results,
        )

        # Post review to GitHub
        self._post_review(pr_number, review_result)

        self._log.info(
            "review_completed",
            pr_number=pr_number,
            decision=review_result.decision.value,
            issues_count=len(review_result.issues),
        )

        return review_result

    def check_and_decide(
        self,
        pr_number: int,
        issue_number: int | None = None,
    ) -> dict[str, Any]:
        """
        Check PR status and decide on next action.

        Always performs AI code review regardless of CI status.

        Args:
            pr_number: PR number
            issue_number: Related issue number

        Returns:
            Dict with decision and next action
        """
        pr_info = self._pr_manager.get_pr_info(pr_number)

        # Check CI status first - if still running, wait
        if not pr_info.ci_completed:
            return {
                "action": "wait",
                "reason": "CI checks still running",
                "ci_status": [
                    {"name": c.name, "status": c.status}
                    for c in pr_info.ci_status
                ],
            }

        # Always perform AI code review (regardless of CI status)
        review_result = self.review_pr(pr_number, issue_number)

        # Build response with both CI and review info
        ci_failed = not pr_info.ci_passed
        review_has_issues = review_result.decision == ReviewDecision.CHANGES_REQUESTED

        # Collect failed CI checks
        failed_checks = []
        if ci_failed:
            failed_checks = [
                {
                    "name": c.name,
                    "conclusion": c.conclusion,
                    "output": c.output,
                }
                for c in pr_info.failed_checks
            ]

        # Collect review issues
        review_issues = [
            {
                "severity": i.severity,
                "description": i.description,
                "file": i.file,
                "line": i.line,
                "suggestion": i.suggestion,
            }
            for i in review_result.issues
        ]

        # Decide action
        if ci_failed or review_has_issues:
            action = "fix_ci" if ci_failed else "request_fixes"
            reason_parts = []
            if ci_failed:
                reason_parts.append("CI checks failed")
            if review_has_issues:
                reason_parts.append("code review found issues")

            return {
                "action": action,
                "reason": " and ".join(reason_parts).capitalize(),
                "failed_checks": failed_checks,
                "review_summary": review_result.summary,
                "issues": review_issues,
            }
        else:
            return {
                "action": "merge",
                "reason": "CI passed and review approved",
                "review_summary": review_result.summary,
            }

    def _generate_review(
        self,
        pr_info: PRInfo,
        issue_description: str,
        ci_results: str,
    ) -> ReviewResult:
        """Generate review using LLM."""
        prompt = format_code_review_prompt(
            issue_description=issue_description or "No specific requirements provided.",
            diff=pr_info.diff,
            changed_files=pr_info.files,
            ci_results=ci_results,
        )

        response = self._llm.generate(
            prompt=prompt,
            system_prompt=CODE_REVIEW_SYSTEM,
            temperature=0.3,
        )

        # Parse the review response
        return self._parse_review_response(response.content)

    def _parse_review_response(self, content: str) -> ReviewResult:
        """Parse LLM review response into structured format."""
        # Extract decision
        decision = ReviewDecision.COMMENT
        if "Status: APPROVED" in content or "## Status: APPROVED" in content:
            decision = ReviewDecision.APPROVED
        elif "Status: CHANGES_REQUESTED" in content or "CHANGES_REQUESTED" in content:
            decision = ReviewDecision.CHANGES_REQUESTED

        # Extract summary
        summary = "Review completed."
        summary_match = re.search(
            r"##\s*Summary\s*\n(.*?)(?=\n##|\n\*\*Status|\Z)",
            content,
            re.DOTALL | re.IGNORECASE,
        )
        if summary_match:
            summary = summary_match.group(1).strip()

        # Extract issues
        issues = self._parse_issues(content)

        # Extract positive aspects
        positive = []
        positive_match = re.search(
            r"##\s*Positive Aspects?\s*\n(.*?)(?=\n##|\Z)",
            content,
            re.DOTALL | re.IGNORECASE,
        )
        if positive_match:
            positive = self._parse_list_items(positive_match.group(1))

        # Extract recommendations
        recommendations = []
        rec_match = re.search(
            r"##\s*Recommendations?\s*\n(.*?)(?=\n##|\Z)",
            content,
            re.DOTALL | re.IGNORECASE,
        )
        if rec_match:
            recommendations = self._parse_list_items(rec_match.group(1))

        # Adjust decision based on issues
        if not issues and decision == ReviewDecision.COMMENT:
            decision = ReviewDecision.APPROVED

        if any(i.severity == "CRITICAL" for i in issues):
            decision = ReviewDecision.CHANGES_REQUESTED

        return ReviewResult(
            decision=decision,
            summary=summary,
            issues=issues,
            positive_aspects=positive,
            recommendations=recommendations,
            raw_review=content,
        )

    def _parse_issues(self, content: str) -> list[ReviewIssue]:
        """Parse issues from review content."""
        issues = []

        # Pattern for issue blocks
        issue_pattern = r"\[?(CRITICAL|MAJOR|MINOR)\]?\s*[-:]\s*(.+?)(?=\n\s*\[?(?:CRITICAL|MAJOR|MINOR)|##|\Z)"
        matches = re.findall(issue_pattern, content, re.DOTALL | re.IGNORECASE)

        for severity, details in matches:
            severity = severity.upper()
            details = details.strip()

            # Try to extract file and line
            file_match = re.search(r"File:\s*`?([^`\n]+)`?", details)
            line_match = re.search(r"Line:\s*(\d+)", details)
            suggestion_match = re.search(r"Suggestion:\s*(.+?)(?=\n|$)", details, re.DOTALL)

            # Get description (first line or everything before File:)
            description = details.split("\n")[0].strip()
            if file_match:
                description = details[: details.find("File:")].strip()
            description = re.sub(r"^[-*]\s*", "", description)

            issues.append(ReviewIssue(
                severity=severity,
                description=description,
                file=file_match.group(1).strip() if file_match else None,
                line=int(line_match.group(1)) if line_match else None,
                suggestion=suggestion_match.group(1).strip() if suggestion_match else None,
            ))

        return issues

    def _parse_list_items(self, text: str) -> list[str]:
        """Parse markdown list items."""
        items = []
        for line in text.strip().split("\n"):
            line = line.strip()
            line = re.sub(r"^[-*]\s*", "", line)
            if line:
                items.append(line)
        return items

    def _format_ci_results(self, pr_info: PRInfo) -> str:
        """Format CI results for prompt."""
        if not pr_info.ci_status:
            return "No CI checks configured."

        lines = ["CI/CD Status:"]
        for check in pr_info.ci_status:
            status_icon = "✅" if check.conclusion == "success" else "❌"
            lines.append(f"- {status_icon} {check.name}: {check.conclusion or check.status}")
            if check.output and check.output.get("summary"):
                lines.append(f"  Output: {check.output['summary'][:200]}")

        overall = "All checks passed" if pr_info.ci_passed else "Some checks failed"
        lines.append(f"\nOverall: {overall}")

        return "\n".join(lines)

    def _post_review(self, pr_number: int, review: ReviewResult) -> None:
        """Post review to GitHub."""
        comment_body = review.to_github_comment()

        # Determine GitHub review event
        if review.decision == ReviewDecision.APPROVED:
            event = "APPROVE"
        elif review.decision == ReviewDecision.CHANGES_REQUESTED:
            event = "REQUEST_CHANGES"
        else:
            event = "COMMENT"

        self._pr_manager.add_review_comment(
            pr_number=pr_number,
            body=comment_body,
            event=event,
        )
