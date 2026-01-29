"""Issue parsing and requirements extraction."""

import re
from dataclasses import dataclass, field
from enum import Enum

import structlog
from github.Issue import Issue

logger = structlog.get_logger()


class TaskType(str, Enum):
    """Types of tasks that can be extracted from issues."""

    FEATURE = "feature"
    BUG_FIX = "bug_fix"
    REFACTOR = "refactor"
    DOCUMENTATION = "documentation"
    TEST = "test"
    UNKNOWN = "unknown"


@dataclass
class ParsedIssue:
    """Parsed issue data with extracted requirements."""

    number: int
    title: str
    body: str
    task_type: TaskType
    requirements: list[str]
    acceptance_criteria: list[str]
    mentioned_files: list[str]
    labels: list[str]
    raw_issue: Issue | None = None
    metadata: dict[str, str] = field(default_factory=dict)

    @property
    def full_description(self) -> str:
        """Get full issue description for LLM context."""
        parts = [
            f"# Issue #{self.number}: {self.title}",
            "",
            "## Description",
            self.body,
            "",
        ]

        if self.requirements:
            parts.extend([
                "## Requirements",
                *[f"- {req}" for req in self.requirements],
                "",
            ])

        if self.acceptance_criteria:
            parts.extend([
                "## Acceptance Criteria",
                *[f"- {ac}" for ac in self.acceptance_criteria],
                "",
            ])

        if self.mentioned_files:
            parts.extend([
                "## Referenced Files",
                *[f"- `{f}`" for f in self.mentioned_files],
                "",
            ])

        return "\n".join(parts)


class IssueParser:
    """Parser for extracting structured data from GitHub issues."""

    # Patterns for file references
    FILE_PATTERNS = [
        r"`([a-zA-Z0-9_\-./]+\.[a-zA-Z0-9]+)`",  # `file.ext`
        r"(?:file|in|at|see|modify|edit|update|create)\s+[`'\"]?([a-zA-Z0-9_\-./]+\.[a-zA-Z0-9]+)[`'\"]?",
    ]

    # Patterns for requirements sections
    REQUIREMENTS_PATTERNS = [
        r"(?:##?\s*)?(?:requirements?|needs?|must have|should have)[:\s]*\n((?:[-*]\s*.+\n?)+)",
        r"(?:##?\s*)?(?:tasks?|todo)[:\s]*\n((?:[-*]\s*.+\n?)+)",
    ]

    # Patterns for acceptance criteria
    ACCEPTANCE_PATTERNS = [
        r"(?:##?\s*)?(?:acceptance criteria|ac|done when|complete when)[:\s]*\n((?:[-*]\s*.+\n?)+)",
        r"(?:##?\s*)?(?:expected behavior|expected result)[:\s]*\n((?:[-*]\s*.+\n?)+)",
    ]

    # Keywords for task type detection
    TASK_TYPE_KEYWORDS = {
        TaskType.BUG_FIX: ["bug", "fix", "error", "issue", "broken", "crash", "fail"],
        TaskType.FEATURE: ["add", "implement", "create", "new", "feature", "support"],
        TaskType.REFACTOR: ["refactor", "improve", "optimize", "clean", "restructure"],
        TaskType.DOCUMENTATION: ["doc", "readme", "comment", "documentation"],
        TaskType.TEST: ["test", "spec", "coverage", "unittest"],
    }

    def __init__(self) -> None:
        self._log = logger.bind(component="issue_parser")

    def parse(self, issue: Issue) -> ParsedIssue:
        """
        Parse a GitHub issue into structured data.

        Args:
            issue: GitHub Issue object

        Returns:
            ParsedIssue with extracted data
        """
        body = issue.body or ""
        title = issue.title

        self._log.debug("parsing_issue", issue_number=issue.number, title=title)

        # Extract components
        task_type = self._detect_task_type(title, body)
        requirements = self._extract_requirements(body)
        acceptance_criteria = self._extract_acceptance_criteria(body)
        mentioned_files = self._extract_file_references(body)
        labels = [label.name for label in issue.labels]

        parsed = ParsedIssue(
            number=issue.number,
            title=title,
            body=body,
            task_type=task_type,
            requirements=requirements,
            acceptance_criteria=acceptance_criteria,
            mentioned_files=mentioned_files,
            labels=labels,
            raw_issue=issue,
        )

        self._log.info(
            "issue_parsed",
            issue_number=issue.number,
            task_type=task_type.value,
            requirements_count=len(requirements),
            files_mentioned=len(mentioned_files),
        )

        return parsed

    def _detect_task_type(self, title: str, body: str) -> TaskType:
        """Detect the type of task from title and body."""
        combined_text = f"{title} {body}".lower()

        # Check labels first if available
        for task_type, keywords in self.TASK_TYPE_KEYWORDS.items():
            for keyword in keywords:
                if keyword in combined_text:
                    return task_type

        return TaskType.UNKNOWN

    def _extract_requirements(self, body: str) -> list[str]:
        """Extract requirements from issue body."""
        requirements = []

        for pattern in self.REQUIREMENTS_PATTERNS:
            matches = re.findall(pattern, body, re.IGNORECASE | re.MULTILINE)
            for match in matches:
                items = self._parse_list_items(match)
                requirements.extend(items)

        # Deduplicate while preserving order
        seen = set()
        unique = []
        for req in requirements:
            if req not in seen:
                seen.add(req)
                unique.append(req)

        return unique

    def _extract_acceptance_criteria(self, body: str) -> list[str]:
        """Extract acceptance criteria from issue body."""
        criteria = []

        for pattern in self.ACCEPTANCE_PATTERNS:
            matches = re.findall(pattern, body, re.IGNORECASE | re.MULTILINE)
            for match in matches:
                items = self._parse_list_items(match)
                criteria.extend(items)

        # Deduplicate
        seen = set()
        unique = []
        for ac in criteria:
            if ac not in seen:
                seen.add(ac)
                unique.append(ac)

        return unique

    def _extract_file_references(self, body: str) -> list[str]:
        """Extract file references from issue body."""
        files = set()

        for pattern in self.FILE_PATTERNS:
            matches = re.findall(pattern, body, re.IGNORECASE)
            for match in matches:
                # Filter out common false positives
                if self._is_valid_file_reference(match):
                    files.add(match)

        return sorted(files)

    def _parse_list_items(self, text: str) -> list[str]:
        """Parse markdown list items from text."""
        items = []
        for line in text.strip().split("\n"):
            line = line.strip()
            # Remove list markers
            line = re.sub(r"^[-*]\s+", "", line)
            line = re.sub(r"^\d+\.\s+", "", line)
            if line:
                items.append(line)
        return items

    def _is_valid_file_reference(self, ref: str) -> bool:
        """Check if a string is a valid file reference."""
        # Filter out common false positives
        invalid_patterns = [
            r"^https?://",  # URLs
            r"^\d+\.\d+\.\d+",  # Version numbers
            r"^[a-zA-Z]+@",  # Email-like
        ]

        for pattern in invalid_patterns:
            if re.match(pattern, ref):
                return False

        # Check for valid file extension
        valid_extensions = {
            ".py", ".js", ".ts", ".jsx", ".tsx", ".json", ".yaml", ".yml",
            ".md", ".txt", ".html", ".css", ".scss", ".sql", ".sh",
            ".toml", ".ini", ".cfg", ".env", ".dockerfile",
        }

        ext = "." + ref.split(".")[-1].lower() if "." in ref else ""
        return ext in valid_extensions or "/" in ref
