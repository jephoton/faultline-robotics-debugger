from __future__ import annotations

import fnmatch
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVERLESS = ROOT / "deploy" / "serverless"
BASE_IMAGE = (
    "ghcr.io/allenai/vla-evaluation-harness/libero"
    "@sha256:d0c45bc5a3720d569180e6b8dd92510da895f16c3cc509ccc76e4b4ffbb9e0f0"
)
BRIDGE_SHA = "35f1200eb15608aa898f727a3722f7eef889c6cd"
LEROBOT_SHA = "30da8e687a6dfc617fcd94afc367ac7071c376ce"
PYTORCH_CUDA_INDEX = "https://download.pytorch.org/whl/cu128"


def _dockerignore_includes(rules: list[str], candidate: str) -> bool:
    """Evaluate ordered Docker path globs, including excluded-parent traversal."""
    def matches(pattern: str, path: str) -> bool:
        pattern_parts = pattern.strip("/").split("/")
        path_parts = path.strip("/").split("/")

        def visit(pattern_index: int, path_index: int) -> bool:
            if pattern_index == len(pattern_parts):
                return path_index == len(path_parts)
            if pattern_parts[pattern_index] == "**":
                return visit(pattern_index + 1, path_index) or (
                    path_index < len(path_parts)
                    and visit(pattern_index, path_index + 1)
                )
            return (
                path_index < len(path_parts)
                and fnmatch.fnmatchcase(path_parts[path_index], pattern_parts[pattern_index])
                and visit(pattern_index + 1, path_index + 1)
            )

        return visit(0, 0)

    def path_is_included(path: str) -> bool:
        included = True
        for raw_rule in rules:
            rule = raw_rule.strip()
            if not rule or rule.startswith("#"):
                continue
            negate = rule.startswith("!")
            pattern = rule[1:] if negate else rule
            if matches(pattern, path):
                included = negate
        return included

    path_parts = candidate.strip("/").split("/")
    return all(
        path_is_included("/".join(path_parts[:depth]))
        for depth in range(1, len(path_parts) + 1)
    )


class ServerlessImageContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dockerfile = self._read_or_empty(SERVERLESS / "Dockerfile")
        self.ignore_rules = self._read_or_empty(
            SERVERLESS / "Dockerfile.dockerignore"
        ).splitlines()
        self.requirements = self._read_or_empty(
            SERVERLESS / "requirements-model.txt"
        ).splitlines()

    @staticmethod
    def _read_or_empty(path: Path) -> str:
        return path.read_text(encoding="utf-8") if path.is_file() else ""

    def test_image_pins_simulator_base_and_both_sources(self) -> None:
        self.assertIn(f"FROM {BASE_IMAGE}", self.dockerfile)
        self.assertIn(BRIDGE_SHA, self.dockerfile)
        self.assertIn(LEROBOT_SHA, "\n".join(self.requirements))
        self.assertIn("rev-parse HEAD", self.dockerfile)
        self.assertIn("3.12.13", self.dockerfile)

    def test_model_environment_isolated_and_simulator_entrypoint_fixed(self) -> None:
        self.assertIn("/opt/model-env", self.dockerfile)
        self.assertIn('test "$(/usr/local/bin/uv --version)" = "uv 0.11.25"', self.dockerfile)
        self.assertEqual(self.dockerfile.count("uv pip install --python /opt/model-env/bin/python"), 2)
        self.assertIn("/opt/conda/envs/libero/bin/python", self.dockerfile)
        self.assertIn("/opt/robot-debug/scripts/run_serverless_workload.py", self.dockerfile)
        self.assertIn("/etc/faultline/workload.json", self.dockerfile)
        self.assertIn("ENTRYPOINT []", self.dockerfile)
        self.assertIn('SHELL ["/bin/sh", "-c"]', self.dockerfile)
        self.assertNotRegex(self.dockerfile, r"(?m)^ENV\s+PYTHONPATH=")
        self.assertNotRegex(self.dockerfile, r"(?m)^ARG\s+[^=]*(?:TOKEN|KEY|SECRET)")
        self.assertNotRegex(self.dockerfile, r"(?m)^ENV\s+[^=]*(?:TOKEN|KEY|SECRET)=")

    def test_all_122_resolved_requirements_are_pinned_and_routed(self) -> None:
        requirements = [line.strip() for line in self.requirements if line.strip()]
        evidence = (ROOT / "docs" / "research" / "2026-10-09-serverless-package-resolution.md").read_text(encoding="utf-8")
        resolved_data = evidence.split("```text\n", 1)[1].split("\n```", 1)[0].splitlines()
        self.assertEqual(len(requirements), 122)
        self.assertEqual(len(set(requirements)), 122)
        self.assertEqual(requirements, resolved_data)
        direct_refs = {
            "lerobot[groot] @ git+https://github.com/huggingface/lerobot.git@"
            + LEROBOT_SHA,
            "vla-eval @ git+https://github.com/allenai/vla-evaluation-harness.git@"
            + BRIDGE_SHA,
        }
        for requirement in requirements:
            if requirement not in direct_refs:
                self.assertRegex(requirement, r"^[A-Za-z0-9_.-]+(?:\[[^]]+\])?==")
        self.assertIn(
            "lerobot[groot] @ git+https://github.com/huggingface/lerobot.git@"
            + LEROBOT_SHA,
            requirements,
        )
        self.assertIn(
            "vla-eval @ git+https://github.com/allenai/vla-evaluation-harness.git@"
            + BRIDGE_SHA,
            requirements,
        )
        self.assertIn("torch==2.11.0+cu128", requirements)
        self.assertIn("torchvision==0.26.0+cu128", requirements)
        self.assertIn("torchcodec==0.11.1", requirements)
        self.assertIn(PYTORCH_CUDA_INDEX, self.dockerfile)
        self.assertIn("--exclude-newer 2026-07-04T00:00:00Z", self.dockerfile)

    def test_docker_context_allows_only_required_roots_and_blocks_private_fixtures(self) -> None:
        fixtures = {
            "src/robot_debug/job_runtime.py": True,
            "scripts/run_serverless_workload.py": True,
            "configs/serverless-job.example.json": True,
            "deploy/serverless/requirements-model.txt": True,
            "pyproject.toml": True,
            "LICENSE": True,
            ".git/config": False,
            ".env": False,
            "src/robot_debug/.env.production": False,
            "src/robot_debug/cloud.local.json": False,
            "scripts/argument-preview.json": False,
            "scripts/.aws/credentials": False,
            "src/robot_debug/.ssh/id_ed25519": False,
            "configs/.netrc": False,
            "configs/model-token.json": False,
            "configs/private-key.pem": False,
            "artifacts/run.json": False,
            "datasets/sample.json": False,
            "model-cache/weights.safetensors": False,
            "README.md": False,
        }
        for path, expected in fixtures.items():
            with self.subTest(path=path):
                self.assertEqual(_dockerignore_includes(self.ignore_rules, path), expected)
        self.assertFalse(
            _dockerignore_includes(["**", "!src/robot_debug/*.py"], "src/robot_debug/job_runtime.py")
        )

        first_allow = next(i for i, line in enumerate(self.ignore_rules) if line.startswith("!"))
        later_private_blocks = [
            i
            for i, line in enumerate(self.ignore_rules)
            if line.strip().startswith("**/")
        ]
        self.assertTrue(later_private_blocks)
        self.assertGreater(min(later_private_blocks), first_allow)

    def test_dockerfile_never_copies_context_wildcard_and_records_import_probe(self) -> None:
        self.assertNotRegex(self.dockerfile, r"(?m)^COPY\s+\.\s+")
        self.assertRegex(self.dockerfile, r"(?m)^COPY\s+src\s+/opt/robot-debug/src")
        self.assertRegex(self.dockerfile, r"(?m)^COPY\s+scripts\s+/opt/robot-debug/scripts")
        self.assertIn("import torchcodec", self.dockerfile)
        self.assertIn("GrootPolicy", self.dockerfile)
        self.assertIn("vla_eval.model_servers.lerobot", self.dockerfile)
        self.assertIn("simulator-packages.json", self.dockerfile)
        self.assertIn("model-packages.json", self.dockerfile)
        self.assertNotIn("from_pretrained", self.dockerfile)
        self.assertNotRegex(self.dockerfile, r"(?m)^COPY\s+.*(?:weights|cache|\.env)")
        self.assertIn("apt-get install -y --no-install-recommends ffmpeg", self.dockerfile)


if __name__ == "__main__":
    unittest.main()
