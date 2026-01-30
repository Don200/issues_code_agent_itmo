import subprocess
import unittest

class TestDependencyInstallation(unittest.TestCase):
    def test_uv_installation(self):
        """Test that uv can install dependencies without errors."""
        try:
            subprocess.run(['uv', 'install'], check=True)
        except subprocess.CalledProcessError as e:
            self.fail(f"uv installation failed: {e}")

if __name__ == '__main__':
    unittest.main()