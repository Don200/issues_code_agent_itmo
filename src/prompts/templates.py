"""Prompt templates for SDLC agents."""

# System prompts
ISSUE_ANALYSIS_SYSTEM = """You are a senior software engineer analyzing GitHub issues.
Your task is to understand requirements and plan implementation.

When analyzing an issue:
1. Identify the core problem or feature request
2. List concrete technical requirements
3. Identify files that need to be created or modified
4. Consider edge cases and error handling
5. Think about testing requirements

Be precise and technical in your analysis."""


CODE_GENERATION_SYSTEM = """You are an expert software developer.
Your task is to write clean, production-ready code that solves the given problem.

Guidelines:
1. Write clear, self-documenting code with meaningful names
2. Follow the existing code style and patterns in the repository
3. Include proper error handling
4. Add type hints for Python code
5. Keep functions small and focused
6. Don't over-engineer - solve the problem simply

Output format:
For each file you need to create or modify, output:
```
### FILE: path/to/file.py
```python
<code here>
```
```

If modifying an existing file, include the complete new version of the file."""


CODE_REVIEW_SYSTEM = """You are a senior code reviewer performing automated code review.
Analyze the provided code changes against the original requirements.

Check for:
1. Correctness - Does the code solve the stated problem?
2. Code Quality - Is the code clean, readable, and maintainable?
3. Error Handling - Are edge cases and errors handled properly?
4. Security - Are there any security vulnerabilities?
5. Performance - Are there obvious performance issues?
6. Testing - Is the code testable? Are tests included if needed?
7. Requirements Match - Does implementation match all requirements?

Output your review in this format:
```
## Summary
<Brief summary of changes and overall assessment>

## Status: [APPROVED/CHANGES_REQUESTED]

## Issues Found
- [CRITICAL/MAJOR/MINOR] <issue description>
  - File: <filename>
  - Line: <line number if applicable>
  - Suggestion: <how to fix>

## Positive Aspects
- <what was done well>

## Recommendations
- <optional improvements>
```"""


FIX_ITERATION_SYSTEM = """You are a software developer fixing code based on review feedback.
You will receive the original requirements, your previous implementation, and review comments.

Your task:
1. Understand each issue raised in the review
2. Fix all CRITICAL and MAJOR issues
3. Address MINOR issues if straightforward
4. Maintain the overall code structure unless the review suggests otherwise
5. Don't introduce new issues while fixing

Output the corrected code in the same format as before:
```
### FILE: path/to/file.py
```python
<corrected code>
```
```"""


def format_code_generation_prompt(
    issue_description: str,
    repository_structure: str,
    existing_files: dict[str, str],
    additional_context: str = "",
) -> str:
    """
    Format a prompt for code generation.

    Args:
        issue_description: Parsed issue description with requirements
        repository_structure: File structure of the repository
        existing_files: Dict of filepath -> content for relevant files
        additional_context: Any additional context

    Returns:
        Formatted prompt string
    """
    parts = [
        "# Task",
        "",
        issue_description,
        "",
        "# Repository Structure",
        "",
        "```",
        repository_structure,
        "```",
        "",
    ]

    if existing_files:
        parts.extend([
            "# Relevant Existing Files",
            "",
        ])
        for filepath, content in existing_files.items():
            parts.extend([
                f"## {filepath}",
                "```python" if filepath.endswith(".py") else "```",
                content,
                "```",
                "",
            ])

    if additional_context:
        parts.extend([
            "# Additional Context",
            "",
            additional_context,
            "",
        ])

    parts.extend([
        "# Instructions",
        "",
        "Based on the task requirements and existing code:",
        "1. Implement the required changes",
        "2. Create any new files needed",
        "3. Update existing files if necessary",
        "4. Include any necessary tests",
        "",
        "Output your implementation using the file format specified in the system prompt.",
    ])

    return "\n".join(parts)


def format_code_review_prompt(
    issue_description: str,
    diff: str,
    changed_files: list[dict],
    ci_results: str = "",
) -> str:
    """
    Format a prompt for code review.

    Args:
        issue_description: Original issue description
        diff: Git diff of changes
        changed_files: List of changed file info
        ci_results: CI/CD results if available

    Returns:
        Formatted prompt string
    """
    parts = [
        "# Original Requirements",
        "",
        issue_description,
        "",
        "# Changes to Review",
        "",
        "## Files Changed",
        "",
    ]

    for file in changed_files:
        status_icon = {"added": "➕", "modified": "📝", "removed": "➖"}.get(
            file.get("status", ""), "📄"
        )
        parts.append(
            f"- {status_icon} `{file['filename']}` "
            f"(+{file.get('additions', 0)}/-{file.get('deletions', 0)})"
        )

    parts.extend([
        "",
        "## Diff",
        "",
        "```diff",
        diff,
        "```",
        "",
    ])

    if ci_results:
        parts.extend([
            "# CI/CD Results",
            "",
            ci_results,
            "",
        ])

    parts.extend([
        "# Review Task",
        "",
        "Please review the changes above against the original requirements.",
        "Check for correctness, code quality, security, and completeness.",
        "Output your review in the format specified in the system prompt.",
    ])

    return "\n".join(parts)


def format_fix_prompt(
    issue_description: str,
    previous_implementation: str,
    review_feedback: str,
    iteration: int,
) -> str:
    """
    Format a prompt for fixing code based on review feedback.

    Args:
        issue_description: Original issue description
        previous_implementation: Previous code that was reviewed
        review_feedback: Feedback from the review
        iteration: Current iteration number

    Returns:
        Formatted prompt string
    """
    parts = [
        f"# Fix Iteration {iteration}",
        "",
        "## Original Requirements",
        "",
        issue_description,
        "",
        "## Previous Implementation",
        "",
        previous_implementation,
        "",
        "## Review Feedback",
        "",
        review_feedback,
        "",
        "## Instructions",
        "",
        "Please fix the issues identified in the review feedback.",
        "Focus on CRITICAL and MAJOR issues first.",
        "Output the corrected files using the standard file format.",
    ]

    return "\n".join(parts)
