"""Keep the optional YAML dependency available in clean CI installs."""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ServerlessDependencyContractTests(unittest.TestCase):
    def test_serverless_extra_declares_tested_yaml_dependency(self):
        metadata = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn('[project.optional-dependencies]', metadata)
        self.assertIn('serverless = ["PyYAML==6.0.3"]', metadata)

    def test_ci_installs_the_serverless_extra(self):
        workflow = (ROOT / ".github/workflows/test.yml").read_text(encoding="utf-8")
        self.assertIn('python -m pip install ".[serverless]"', workflow)


if __name__ == "__main__":
    unittest.main()
