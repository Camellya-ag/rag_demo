from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path


@unittest.skipUnless(os.name == "nt", "PowerShell runner is Windows-specific")
class OfflineRunnerTests(unittest.TestCase):
    def test_failed_test_process_is_not_reported_as_success(self) -> None:
        script = Path(__file__).resolve().parents[1] / "scripts" / "run_offline_tests.ps1"
        with tempfile.TemporaryDirectory() as directory:
            fake_python = Path(directory) / "failed-python.cmd"
            fake_python.write_text("@exit /b 7\n", encoding="ascii")
            result = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(script), "-Python", str(fake_python)],
                capture_output=True,
                text=True,
                timeout=15,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        self.assertEqual(result.returncode, 7, result.stdout + result.stderr)
