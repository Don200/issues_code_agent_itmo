"""Tests for state machine."""

import pytest

from src.core.state_machine import IssueContext, IssueState, IssueStateMachine


@pytest.fixture
def context() -> IssueContext:
    """Create a test issue context."""
    return IssueContext(
        issue_number=1,
        issue_title="Test Issue",
        issue_body="Test body",
    )


@pytest.fixture
def state_machine(context: IssueContext) -> IssueStateMachine:
    """Create a state machine instance."""
    return IssueStateMachine(context, max_iterations=3)


def test_initial_state(state_machine: IssueStateMachine) -> None:
    """Test initial state is CREATED."""
    assert state_machine.state == IssueState.CREATED


def test_valid_transition(state_machine: IssueStateMachine) -> None:
    """Test valid state transition."""
    assert state_machine.transition_to(IssueState.ANALYZING)
    assert state_machine.state == IssueState.ANALYZING


def test_invalid_transition(state_machine: IssueStateMachine) -> None:
    """Test invalid state transition is rejected."""
    # Can't go directly from CREATED to COMPLETED
    assert not state_machine.transition_to(IssueState.COMPLETED)
    assert state_machine.state == IssueState.CREATED


def test_transition_history(state_machine: IssueStateMachine) -> None:
    """Test transition history is recorded."""
    state_machine.transition_to(IssueState.ANALYZING)
    state_machine.transition_to(IssueState.CONTEXT_BUILDING)

    history = state_machine.history
    assert len(history) == 2
    assert history[0].from_state == IssueState.CREATED
    assert history[0].to_state == IssueState.ANALYZING
    assert history[1].from_state == IssueState.ANALYZING
    assert history[1].to_state == IssueState.CONTEXT_BUILDING


def test_terminal_state_detection(state_machine: IssueStateMachine) -> None:
    """Test terminal state detection."""
    assert not state_machine.is_terminal

    # Navigate to COMPLETED
    state_machine.transition_to(IssueState.ANALYZING)
    state_machine.transition_to(IssueState.CONTEXT_BUILDING)
    state_machine.transition_to(IssueState.GENERATING_CODE)
    state_machine.transition_to(IssueState.COMMITTING)
    state_machine.transition_to(IssueState.CREATING_PR)
    state_machine.transition_to(IssueState.CI_RUNNING)
    state_machine.transition_to(IssueState.CI_PASSED)
    state_machine.transition_to(IssueState.REVIEWING)
    state_machine.transition_to(IssueState.APPROVED)
    state_machine.transition_to(IssueState.COMPLETED)

    assert state_machine.is_terminal
    assert state_machine.is_success


def test_max_iterations_check(state_machine: IssueStateMachine) -> None:
    """Test max iterations enforcement."""
    # Set up: go through cycle multiple times
    state_machine.transition_to(IssueState.ANALYZING)
    state_machine.transition_to(IssueState.CONTEXT_BUILDING)
    state_machine.transition_to(IssueState.GENERATING_CODE)

    # Simulate iterations
    state_machine.context.iteration = 3  # At max
    state_machine.transition_to(IssueState.COMMITTING)
    state_machine.transition_to(IssueState.CREATING_PR)
    state_machine.transition_to(IssueState.CI_RUNNING)
    state_machine.transition_to(IssueState.CI_FAILED)

    # Trying to go back to GENERATING_CODE should trigger MAX_ITERATIONS_REACHED
    state_machine.transition_to(IssueState.GENERATING_CODE)

    assert state_machine.state == IssueState.MAX_ITERATIONS_REACHED


def test_iteration_increment(state_machine: IssueStateMachine) -> None:
    """Test iteration counter increment."""
    assert state_machine.context.iteration == 0

    new_iteration = state_machine.increment_iteration()

    assert new_iteration == 1
    assert state_machine.context.iteration == 1


def test_summary(state_machine: IssueStateMachine) -> None:
    """Test state machine summary."""
    state_machine.transition_to(IssueState.ANALYZING)
    state_machine.context.pr_number = 42
    state_machine.context.branch_name = "feature-branch"

    summary = state_machine.get_summary()

    assert summary["issue_number"] == 1
    assert summary["current_state"] == "analyzing"
    assert summary["pr_number"] == 42
    assert summary["branch_name"] == "feature-branch"
    assert summary["is_terminal"] is False


def test_can_transition_to(state_machine: IssueStateMachine) -> None:
    """Test can_transition_to check."""
    assert state_machine.can_transition_to(IssueState.ANALYZING)
    assert not state_machine.can_transition_to(IssueState.COMPLETED)
