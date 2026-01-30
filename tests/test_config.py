import subprocess
import unittest

class TestDependencyInstallation(unittest.TestCase):
    def test_uv_installation(self):
        """Test if uv is installed correctly."""
        result = subprocess.run(['uv', '--version'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        self.assertIn('uv', result.stdout)

if __name__ == '__main__':
    unittest.main()