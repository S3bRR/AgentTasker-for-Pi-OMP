"""Public package/documentation contracts; no registry publication is assumed."""
import json
from pathlib import Path
import re
import unittest

from agent_tasker_mcp.models import TaskType
from agent_tasker_mcp.registry import validate_payload
from agent_tasker_mcp.remote import validate_config

ROOT = Path(__file__).resolve().parents[1]


class PackagingTests(unittest.TestCase):
    def test_package_metadata_and_runtime_dependencies(self):
        metadata = (ROOT / "pyproject.toml").read_text()
        self.assertIn('name = "agent-tasker-pi-omp"', metadata)
        self.assertIn('requires-python = ">=3.10"', metadata)
        self.assertIn('agent-tasker = "agent_tasker_mcp.server:cli"', metadata)
        self.assertIn('agent-tasker-doctor = "agent_tasker_mcp.doctor:main"', metadata)
        project = metadata.split('[project.optional-dependencies]')[0]
        self.assertNotRegex(project, r"(?m)^dependencies\s*=")
        self.assertFalse((ROOT / "server.json").exists(), "Do not claim an unregistered registry/PyPI package")

    def test_documented_examples_validate(self):
        providers = json.loads((ROOT / "examples/brave-providers.json").read_text())
        validate_payload(TaskType.DISCOVERY_SEARCH, {"query": "test", "providers": providers})
        remote = json.loads((ROOT / "examples/fetch-mcp.json").read_text())
        validate_config(remote["mcpServers"])
        for filename in ("ten-searches.json", "five-mcp-calls.json", "four-shell-jobs.json"):
            batch = json.loads((ROOT / "examples" / filename).read_text())
            for task in batch["tasks"]:
                if task["task_type"] == "discovery_search":
                    task["providers"] = providers
                validate_payload(TaskType(task["task_type"]), task)

    def test_local_documentation_links_resolve(self):
        for file in [*ROOT.glob("*.md"), *ROOT.glob("docs/*.md")]:
            for target in re.findall(r"\]\(([^)\s]+)\)", file.read_text()):
                if "://" in target or target.startswith("#"):
                    continue
                path = target.split("#")[0]
                self.assertTrue((file.parent / path).exists(), f"Broken link in {file.name}: {target}")

    def test_ci_runs_tests_and_clean_install_without_publication(self):
        workflow = (ROOT / ".github/workflows/test.yml").read_text()
        for required in ("ubuntu-latest", "macos-latest", "3.10", "3.12", "unittest discover", "pip install dist/*.whl", "--shell-test"):
            self.assertIn(required, workflow)
        self.assertNotIn("pypi-publish", workflow)
        self.assertNotIn("secrets.", workflow)

    def test_install_prompt_requires_host_selection_and_real_session_verification(self):
        readme = (ROOT / "README.md").read_text()
        self.assertIn("INSTALL.md", readme)
        self.assertIn("SECURITY.md", readme)
        self.assertIn("Ask me for missing choices", readme)
        self.assertIn("real session", readme)
        self.assertIn("not a sandbox", readme)
        self.assertIn("Clawdbot Contributors", (ROOT / "LICENSE").read_text())


if __name__ == "__main__":
    unittest.main()
