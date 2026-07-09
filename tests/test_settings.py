import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from kgnite.settings import load_settings, save_settings, workspace_subdir


class SettingsTests(unittest.TestCase):
    def test_settings_persist_and_create_workspace_roots(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = root / "settings.json"
            workspace = root / "workspace"
            with patch.dict(os.environ, {"KGNITE_SETTINGS_PATH": str(config)}):
                saved = save_settings({"workspace_dir": str(workspace)})
                self.assertEqual(load_settings()["workspace_dir"], str(workspace.resolve()))
                self.assertTrue((workspace / "competitions").is_dir())
                self.assertTrue((workspace / "projects").is_dir())
                self.assertEqual(
                    workspace_subdir("project", "demo"), workspace.resolve() / "projects" / "demo"
                )
                self.assertEqual(json.loads(config.read_text())["workspace_dir"], str(workspace.resolve()))
                self.assertEqual(saved["settings_file"], str(config))


if __name__ == "__main__":
    unittest.main()
