import pytest

def test_uv_dependency_installed() -> None:
    """Test to ensure that uv is installed as a dependency."""
    try:
        import uv
    except ImportError:
        pytest.fail("uv is not installed. Please check your dependencies.")