"""Prompts for LLM interactions."""

from src.prompts.templates import (
    CODE_GENERATION_SYSTEM,
    CODE_REVIEW_SYSTEM,
    ISSUE_ANALYSIS_SYSTEM,
    format_code_generation_prompt,
    format_code_review_prompt,
    format_fix_prompt,
)

__all__ = [
    "CODE_GENERATION_SYSTEM",
    "CODE_REVIEW_SYSTEM",
    "ISSUE_ANALYSIS_SYSTEM",
    "format_code_generation_prompt",
    "format_code_review_prompt",
    "format_fix_prompt",
]
