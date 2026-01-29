"""State machine for Issue lifecycle management."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

import structlog

logger = structlog.get_logger()


class IssueState(str, Enum):
    """States in the Issue lifecycle."""

    # Initial state
    CREATED = "created"

    # Analysis phase
    ANALYZING = "analyzing"
    CONTEXT_BUILDING = "context_building"

    # Development phase
    GENERATING_CODE = "generating_code"
    COMMITTING = "committing"
    CREATING_PR = "creating_pr"

    # CI/CD phase
    CI_RUNNING = "ci_running"
    CI_PASSED = "ci_passed"
    CI_FAILED = "ci_failed"

    # Review phase
    REVIEWING = "reviewing"
    CHANGES_REQUESTED = "changes_requested"
    APPROVED = "approved"

    # Final states
    MERGING = "merging"
    COMPLETED = "completed"
    FAILED = "failed"
    MAX_ITERATIONS_REACHED = "max_iterations_reached"


# Valid state transitions
VALID_TRANSITIONS: dict[IssueState, list[IssueState]] = {
    IssueState.CREATED: [IssueState.ANALYZING],
    IssueState.ANALYZING: [IssueState.CONTEXT_BUILDING, IssueState.FAILED],
    IssueState.CONTEXT_BUILDING: [IssueState.GENERATING_CODE, IssueState.FAILED],
    IssueState.GENERATING_CODE: [IssueState.COMMITTING, IssueState.FAILED],
    IssueState.COMMITTING: [IssueState.CREATING_PR, IssueState.FAILED],
    IssueState.CREATING_PR: [IssueState.CI_RUNNING, IssueState.FAILED],
    IssueState.CI_RUNNING: [IssueState.CI_PASSED, IssueState.CI_FAILED],
    IssueState.CI_PASSED: [IssueState.REVIEWING],
    IssueState.CI_FAILED: [IssueState.GENERATING_CODE, IssueState.FAILED, IssueState.MAX_ITERATIONS_REACHED],
    IssueState.REVIEWING: [IssueState.APPROVED, IssueState.CHANGES_REQUESTED, IssueState.FAILED],
    IssueState.CHANGES_REQUESTED: [
        IssueState.GENERATING_CODE,
        IssueState.FAILED,
        IssueState.MAX_ITERATIONS_REACHED,
    ],
    IssueState.APPROVED: [IssueState.MERGING, IssueState.COMPLETED],
    IssueState.MERGING: [IssueState.COMPLETED, IssueState.FAILED],
    IssueState.COMPLETED: [],
    IssueState.FAILED: [],
    IssueState.MAX_ITERATIONS_REACHED: [],
}


@dataclass
class StateTransition:
    """Record of a state transition."""

    from_state: IssueState
    to_state: IssueState
    timestamp: datetime
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class IssueContext:
    """Context data for an issue being processed."""

    issue_number: int
    issue_title: str
    issue_body: str
    pr_number: int | None = None
    branch_name: str | None = None
    iteration: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


class IssueStateMachine:
    """State machine managing the lifecycle of an Issue through the SDLC pipeline."""

    def __init__(
        self,
        issue_context: IssueContext,
        max_iterations: int = 5,
    ) -> None:
        self.context = issue_context
        self.max_iterations = max_iterations
        self._state = IssueState.CREATED
        self._history: list[StateTransition] = []
        self._log = logger.bind(
            issue_number=issue_context.issue_number,
            component="state_machine",
        )

    @property
    def state(self) -> IssueState:
        """Get current state."""
        return self._state

    @property
    def history(self) -> list[StateTransition]:
        """Get state transition history."""
        return self._history.copy()

    @property
    def is_terminal(self) -> bool:
        """Check if current state is terminal."""
        return self._state in {
            IssueState.COMPLETED,
            IssueState.FAILED,
            IssueState.MAX_ITERATIONS_REACHED,
        }

    @property
    def is_success(self) -> bool:
        """Check if ended in success state."""
        return self._state == IssueState.COMPLETED

    def can_transition_to(self, new_state: IssueState) -> bool:
        """Check if transition to new state is valid."""
        valid_states = VALID_TRANSITIONS.get(self._state, [])
        return new_state in valid_states

    def transition_to(
        self,
        new_state: IssueState,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """
        Transition to a new state.

        Returns True if transition was successful, False otherwise.
        """
        if not self.can_transition_to(new_state):
            self._log.warning(
                "invalid_transition_attempted",
                from_state=self._state.value,
                to_state=new_state.value,
                valid_states=[s.value for s in VALID_TRANSITIONS.get(self._state, [])],
            )
            return False

        # Check iteration limit for retry states
        if new_state == IssueState.GENERATING_CODE and self.context.iteration > 0:
            if self.context.iteration >= self.max_iterations:
                self._log.warning(
                    "max_iterations_reached",
                    iteration=self.context.iteration,
                    max_iterations=self.max_iterations,
                )
                new_state = IssueState.MAX_ITERATIONS_REACHED

        old_state = self._state
        self._state = new_state

        transition = StateTransition(
            from_state=old_state,
            to_state=new_state,
            timestamp=datetime.now(),
            metadata=metadata or {},
        )
        self._history.append(transition)

        self._log.info(
            "state_transition",
            from_state=old_state.value,
            to_state=new_state.value,
            iteration=self.context.iteration,
        )

        return True

    def increment_iteration(self) -> int:
        """Increment iteration counter and return new value."""
        self.context.iteration += 1
        self._log.info("iteration_incremented", iteration=self.context.iteration)
        return self.context.iteration

    def get_summary(self) -> dict[str, Any]:
        """Get summary of state machine status."""
        return {
            "issue_number": self.context.issue_number,
            "current_state": self._state.value,
            "iteration": self.context.iteration,
            "max_iterations": self.max_iterations,
            "is_terminal": self.is_terminal,
            "is_success": self.is_success,
            "pr_number": self.context.pr_number,
            "branch_name": self.context.branch_name,
            "transitions_count": len(self._history),
        }
