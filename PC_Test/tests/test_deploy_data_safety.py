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

    def test_readiness_check_retries_within_a_bounded_window(self):
        """#98：容器启动窗口内 /api/ready 会短暂 503，就绪检查必须有有上界的重试，
        而不是「up 完立刻 curl 一次就定生死」；窗口耗尽仍不就绪时仍要失败退出。"""
        script = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("ready_ok=0", script)
        self.assertIn("for _ in $(seq 1 30); do", script)
        self.assertIn('if [ "$ready_ok" -ne 1 ]; then', script)
        # 重试在匿名探测之前，收尾顺序不变
        self.assertLess(script.index("ready_ok=0"),
                        script.index("Anonymous hardware API status"))


if __name__ == "__main__":
    unittest.main()
