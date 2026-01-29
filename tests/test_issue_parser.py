"""Tests for issue parser."""

from unittest.mock import MagicMock

import pytest

from src.github.issue_parser import IssueParser, TaskType


@pytest.fixture
def parser() -> IssueParser:
    """Create a parser instance."""
    return IssueParser()


@pytest.fixture
def mock_issue() -> MagicMock:
    """Create a mock GitHub issue."""
    issue = MagicMock()
    issue.number = 42
    issue.title = "Add user authentication"
    issue.body = """
## Description
We need to add user authentication to the API.

## Requirements
- Add login endpoint
- Add logout endpoint
- Use JWT tokens

## Acceptance Criteria
- Users can log in with email/password
- JWT token is returned on successful login
- Token expires after 24 hours

## Files to modify
- `src/api/routes.py`
- `src/auth/jwt.py`
"""
    issue.labels = []
    return issue


def test_parse_basic_issue(parser: IssueParser, mock_issue: MagicMock) -> None:
    """Test parsing a basic issue."""
    parsed = parser.parse(mock_issue)

    assert parsed.number == 42
    assert parsed.title == "Add user authentication"
    assert "authentication" in parsed.body.lower()


def test_detect_feature_task_type(parser: IssueParser, mock_issue: MagicMock) -> None:
    """Test detecting feature task type."""
    mock_issue.title = "Add new feature for users"
    parsed = parser.parse(mock_issue)

    assert parsed.task_type == TaskType.FEATURE


def test_detect_bug_task_type(parser: IssueParser, mock_issue: MagicMock) -> None:
    """Test detecting bug fix task type."""
    mock_issue.title = "Fix authentication bug"
    mock_issue.body = "There's a bug in the login system"
    parsed = parser.parse(mock_issue)

    assert parsed.task_type == TaskType.BUG_FIX


def test_extract_requirements(parser: IssueParser, mock_issue: MagicMock) -> None:
    """Test extracting requirements from issue."""
    parsed = parser.parse(mock_issue)

    assert len(parsed.requirements) >= 2
    assert any("login" in req.lower() for req in parsed.requirements)


def test_extract_acceptance_criteria(parser: IssueParser, mock_issue: MagicMock) -> None:
    """Test extracting acceptance criteria."""
    parsed = parser.parse(mock_issue)

    assert len(parsed.acceptance_criteria) >= 2
    assert any("jwt" in ac.lower() for ac in parsed.acceptance_criteria)


def test_extract_file_references(parser: IssueParser, mock_issue: MagicMock) -> None:
    """Test extracting file references."""
    parsed = parser.parse(mock_issue)

    assert "src/api/routes.py" in parsed.mentioned_files
    assert "src/auth/jwt.py" in parsed.mentioned_files


def test_full_description_format(parser: IssueParser, mock_issue: MagicMock) -> None:
    """Test full description formatting."""
    parsed = parser.parse(mock_issue)
    description = parsed.full_description

    assert f"Issue #{parsed.number}" in description
    assert parsed.title in description
    assert "Requirements" in description


def test_empty_body(parser: IssueParser, mock_issue: MagicMock) -> None:
    """Test parsing issue with empty body."""
    mock_issue.body = None
    parsed = parser.parse(mock_issue)

    assert parsed.body == ""
    assert parsed.requirements == []
    assert parsed.acceptance_criteria == []


def test_issue_with_labels(parser: IssueParser, mock_issue: MagicMock) -> None:
    """Test parsing issue with labels."""
    label1 = MagicMock()
    label1.name = "bug"
    label2 = MagicMock()
    label2.name = "priority-high"
    mock_issue.labels = [label1, label2]

    parsed = parser.parse(mock_issue)

    assert "bug" in parsed.labels
    assert "priority-high" in parsed.labels
