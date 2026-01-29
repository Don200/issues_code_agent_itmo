import pytest
from your_project_name.core.state_machine import StateMachine  # Adjust the import based on your project structure

def test_state_machine_initialization():
    """Test initialization of StateMachine."""
    state_machine = StateMachine()
    assert state_machine is not None