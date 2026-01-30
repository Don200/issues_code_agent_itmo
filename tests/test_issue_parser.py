from unittest.mock import MagicMock
import pytest
from src.github.issue_parser import IssueParser

@pytest.fixture
def parser() -> IssueParser:
    """Create a parser instance."""
    return IssueParser()

@pytest.fixture
def mock_issue() -> MagicMock:
    """Create a mock GitHub issue."""
    issue = MagicMock()
    issue.body = "This issue is to add user authentication."
    issue.labels = []
    return issue

def test_parse_basic_issue(parser: IssueParser, mock_issue: MagicMock) -> None:
    """Test parsing a basic issue."""
    parsed = parser.parse(mock_issue)
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

def test_full_description_format(parser: IssueParser, mock_issue: MagicMock) -> None:
    """Test full description formatting."""
    parsed = parser.parse(mock_issue)
    assert parsed.title in parsed.full_description
    assert "Requirements" in parsed.full_description

def test_empty_body(parser: IssueParser, mock_issue: MagicMock) -> None:
    """Test parsing issue with empty body."""
    mock_issue.body = None
    parsed = parser.parse(mock_issue)
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