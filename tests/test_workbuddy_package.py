from __future__ import annotations

import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from package_workbuddy_skill import _project_author, package_workbuddy_skill  # noqa: E402


class WorkBuddyPackageTests(unittest.TestCase):
    def test_project_author_fallback_supports_python_310(self) -> None:
        with patch("package_workbuddy_skill.tomllib", None):
            self.assertEqual(_project_author(ROOT), "Wangge")

    def test_generated_package_has_host_specific_frontmatter_and_portable_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "data-lens-workbuddy.zip"
            result = package_workbuddy_skill(ROOT, output)
            self.assertEqual(result["skill_entry"], "skills/data-lens/SKILL.md")
            with zipfile.ZipFile(output) as archive:
                names = archive.namelist()
                skill = archive.read("skills/data-lens/SKILL.md").decode("utf-8")
            self.assertIn("description_zh:", skill)
            self.assertIn("description_en:", skill)
            self.assertIn(f'version: "{result["version"]}"', skill)
            self.assertIn('author: "Wangge"', skill)
            self.assertTrue(all(name.startswith("skills/data-lens/") for name in names))
            self.assertFalse(any("/.git/" in name or "/dist/" in name for name in names))
            self.assertIn(
                "skills/data-lens/evals/semantic-conformance/probes-public.json",
                names,
            )
            self.assertNotIn(
                "skills/data-lens/evals/semantic-conformance/expectations-private.json",
                names,
            )
            self.assertNotIn(
                "skills/data-lens/tests/test_semantic_conformance.py",
                names,
            )


if __name__ == "__main__":
    unittest.main()
