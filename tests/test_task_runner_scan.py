import shutil
import time
import unittest
from pathlib import Path

from backend.core.task_manager import TaskRunner
from backend.models.sync_task import SyncTask


class TestTaskRunnerScan(unittest.TestCase):
    def setUp(self):
        self.base = Path("./tests/data/task_runner_scan")
        if self.base.exists():
            shutil.rmtree(self.base)
        self.source = self.base / "src"
        self.target = self.base / "dst"
        self.source.mkdir(parents=True)
        self.target.mkdir(parents=True)

        # 构造最小 SyncTask（不落库，仅用于 TaskRunner 初始化）
        self.task = SyncTask(
            id=999,
            name="scan-test",
            source_path=str(self.source),
            target_type="local",
            target_path=str(self.target),
            enabled=True,
            auto_start=False,
            eol_normalize="keep",
            exclude_patterns=[],
            file_extensions=[]
        )

    def tearDown(self):
        if self.base.exists():
            shutil.rmtree(self.base)

    def test_scan_detects_change(self):
        runner = TaskRunner(self.task)
        runner._create_sync_engine()

        p = self.source / "a.txt"
        p.write_text("v1", encoding="utf-8")
        runner._scan_once()
        self.assertTrue((self.target / "a.txt").exists())

        time.sleep(0.01)
        p.write_text("v2", encoding="utf-8")
        runner._scan_once()
        self.assertEqual((self.target / "a.txt").read_text(encoding="utf-8"), "v2")


if __name__ == "__main__":
    unittest.main()
