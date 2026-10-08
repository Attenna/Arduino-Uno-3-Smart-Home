import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "sync_orangepi.sh"


class DeployDataSafetyTests(unittest.TestCase):
    def test_deploy_copies_only_files_tracked_by_the_commit(self):
        script = SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn('cp -a "$REPO_DIR/PC_Test/."', script)
        self.assertIn('archive --format=tar "$commit:PC_Test"', script)

    def test_runtime_state_is_backed_up_before_source_overlay(self):
        script = SCRIPT.read_text(encoding="utf-8")
        backup = script.index('python3 "$RUNTIME_DIR/scripts/backup_state.py"')
        overlay = script.index('archive --format=tar "$commit:PC_Test"')
        self.assertLess(backup, overlay)


if __name__ == "__main__":
    unittest.main()
