import pytest
from your_project_name.github.issue_parser import IssueParser  # Adjust the import based on your project structure

def test_issue_parser_initialization():
    """Test initialization of IssueParser."""
    parser = IssueParser()
    assert parser is not None