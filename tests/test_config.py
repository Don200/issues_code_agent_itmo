import pytest
from your_project_name import config  # Adjust the import based on your project structure

def test_uv_dependency():
    """Test if uv is installed correctly."""
    try:
        import uv
        assert True
    except ImportError:
        assert False, "uv is not installed"