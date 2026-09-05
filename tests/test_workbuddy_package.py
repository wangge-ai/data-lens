from __future__ import annotations

import sys
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from package_workbuddy_skill import package_workbuddy_skill  # noqa: E402


class WorkBuddyPackageTests(unittest.TestCase):
    def test_generated_package_keeps_canonical_frontmatter_and_portable_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "data-lens-workbuddy.zip"
            result = package_workbuddy_skill(ROOT, output)
            self.assertEqual(result["skill_entry"], "SKILL.md")
            with zipfile.ZipFile(output) as archive:
                names = archive.namelist()
                skill = archive.read("SKILL.md").decode("utf-8")
            self.assertEqual(skill, (ROOT / "SKILL.md").read_text(encoding="utf-8"))
            self.assertIn("name: data-lens", skill)
            self.assertIn("description:", skill)
            self.assertFalse(any(name.startswith("skills/data-lens/") for name in names))
            self.assertFalse(any("/.git/" in name or "/dist/" in name for name in names))
            self.assertIn(
                "evals/semantic-conformance/probes-public.json",
                names,
            )
            self.assertIn("references/agent-compatibility.md", names)
            self.assertIn("scripts/data_lens.py", names)
            self.assertNotIn(
                "evals/semantic-conformance/expectations-private.json",
                names,
            )
            self.assertNotIn(
                "tests/test_semantic_conformance.py",
                names,
            )
            self.assertNotIn("tests/test_workbuddy_package.py", names)
            self.assertFalse(any(name.startswith("tests/") for name in names))
            self.assertNotIn("AGENTS.md", names)
            self.assertNotIn("CHANGELOG.md", names)
            self.assertNotIn("agents/openai.yaml", names)
            self.assertFalse(any(name.startswith("evals/cases/") for name in names))

    def test_packaged_skill_can_run_capability_discovery_after_extraction(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "data-lens-workbuddy.zip"
            package_workbuddy_skill(ROOT, output)
            with zipfile.ZipFile(output) as archive:
                archive.extractall(temp_dir)
            installed = Path(temp_dir)
            completed = subprocess.run(
                [sys.executable, str(installed / "scripts" / "data_lens.py"), "capabilities"],
                cwd=installed,
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn('"python_standard_library"', completed.stdout)
            smoke = subprocess.run(
                [sys.executable, str(installed / "scripts" / "data_lens.py"), "test"],
                cwd=installed,
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )
            self.assertEqual(smoke.returncode, 0, smoke.stderr)
            self.assertIn("core smoke suite passed", smoke.stdout)


if __name__ == "__main__":
    unittest.main()
