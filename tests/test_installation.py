import subprocess
import unittest

class TestInstallation(unittest.TestCase):
    def test_uv_installation(self):
        """Test if uv is installed correctly."""
        try:
            result = subprocess.run(['uv', '--version'], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0)
            self.assertIn('uv', result.stdout)
        except FileNotFoundError:
            self.fail("uv is not installed or not found in PATH.")

if __name__ == '__main__':
    unittest.main()