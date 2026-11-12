"""Kiểm tra bộ chạy thí nghiệm (offline, dữ liệu sklearn có sẵn). Bỏ qua nếu thiếu sklearn/scipy."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "experiments"))

try:
    import scipy  # noqa: F401
    import sklearn  # noqa: F401
    HAVE = True
except Exception:  # noqa: BLE001
    HAVE = False

from src.tools.experiments import ResultsError, ablation_grid, load_results, performance_grid  # noqa: E402


@unittest.skipUnless(HAVE, "thiếu scikit-learn/scipy")
class RunnerTests(unittest.TestCase):
    def test_demo_runs_and_schema_is_valid_but_refused_by_default(self):
        import run_experiments as rx
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "results.demo.json"
            self.assertEqual(rx.main(["--demo", "--quick", "--out", str(out)]), 0)
            self.assertTrue(out.with_name("results.demo_raw.csv").exists())
            raw = json.loads(out.read_text(encoding="utf-8"))
            self.assertTrue(raw["_demo"] and raw["_quick"])
            self.assertEqual(raw["seeds"], 2)
            # mặc định bị TỪ CHỐI -> không thể lọt vào bài báo thật
            os.environ.pop("ALLOW_DEMO_RESULTS", None)
            with self.assertRaises(ResultsError):
                load_results(out)
            # nhưng schema hợp lệ với hệ thống
            os.environ["ALLOW_DEMO_RESULTS"] = "1"
            try:
                res = load_results(out)
            finally:
                os.environ.pop("ALLOW_DEMO_RESULTS", None)
            (header, rows), _ = performance_grid(res)
            self.assertEqual(len(rows), 3)
            self.assertIn("±", rows[0][1][0])
            self.assertTrue(res.significance)
            self.assertIsNotNone(ablation_grid(res))
            self.assertTrue(res.has_sensitivity())

    def test_refuses_to_write_demo_into_results_json(self):
        import run_experiments as rx
        with tempfile.TemporaryDirectory() as d, self.assertRaises(SystemExit):
            rx.main(["--demo", "--quick", "--out", str(Path(d) / "results.json")])

    def test_statistics_helpers(self):
        import run_experiments as rx
        m = rx.mean_std([1.0, 2.0, 3.0])
        self.assertAlmostEqual(m["mean"], 2.0)
        self.assertAlmostEqual(m["std"], 1.0)
        self.assertIsNone(rx.paired_ttest([1.0], [2.0]))
        self.assertLess(rx.paired_ttest([0.9, 0.91, 0.92, 0.93], [0.8, 0.81, 0.79, 0.82]), 0.01)


if __name__ == "__main__":
    unittest.main()


# ---------------------------------------------------------------------------------------------------
# Chạy tiếp / thiếu lần chạy / đề tài / Kaggle — không cần sklearn (task thuần Python)
# ---------------------------------------------------------------------------------------------------
import json as _json  # noqa: E402
import subprocess as _sp  # noqa: E402
import textwrap as _tw  # noqa: E402

TINY_TASK = _tw.dedent('''
    import os, random

    def get_task(quick):
        def loader(seed):
            return random.Random(seed).random()

        def good(data, seed):
            return {"Acc": 0.80 + 0.01 * random.Random(seed).random()}

        def prop(data, seed):
            if os.environ.get("FAIL_PROPOSED_SEED") == str(seed) and not os.path.exists(os.environ["FLAG"]):
                open(os.environ["FLAG"], "w").close()
                raise RuntimeError("phiên bị ngắt (giả lập)")
            return {"Acc": 0.85 + 0.01 * random.Random(seed + 100).random()}

        return {
            "datasets": {"D1": loader},
            "metrics": ["Acc"],
            "methods": [{"name": "Base", "run": good}, {"name": "Ours", "proposed": True, "run": prop}],
        }
''')


class ResumeAndTopicTests(unittest.TestCase):
    def setUp(self):
        import run_experiments as rx
        self.rx = rx
        self.tmp = Path(tempfile.mkdtemp(prefix="exp_"))
        self.task = self.tmp / "task.py"
        self.task.write_text(TINY_TASK, encoding="utf-8")
        self.out = self.tmp / "results.json"
        self.flag = self.tmp / "flag"
        os.environ["FLAG"] = str(self.flag)
        os.environ["FAIL_PROPOSED_SEED"] = "2"
        self.addCleanup(lambda: (os.environ.pop("FLAG", None), os.environ.pop("FAIL_PROPOSED_SEED", None)))

    def _run(self, *extra):
        return self.rx.main(["--task", str(self.task), "--out", str(self.out), "--seeds", "4",
                             "--topic", "My Topic", *extra])

    def test_interrupted_run_leaves_no_results_then_resumes_without_recomputing(self):
        self.assertEqual(self._run(), 2)                                  # lần 1: seed 2 của Ours "bị ngắt"
        self.assertFalse(self.out.exists())                               # KHÔNG tạo results.json khi còn thiếu
        partial = _json.loads(self.out.with_name("results.partial.json").read_text(encoding="utf-8"))
        self.assertTrue(partial["_partial"])
        self.assertEqual(len(partial["missing"]), 1)
        log = self.out.with_name("results.runs.jsonl")
        self.assertEqual(len(log.read_text(encoding="utf-8").splitlines()), 7)   # 7/8 lần đã xong được lưu
        self.assertEqual(self._run(), 0)                                  # lần 2: chỉ chạy lại lần thiếu
        self.assertEqual(len(log.read_text(encoding="utf-8").splitlines()), 8)
        res = _json.loads(self.out.read_text(encoding="utf-8"))
        self.assertEqual(res["topic"], "My Topic")
        self.assertEqual(len(res["task_sha256"]), 64)
        self.assertEqual(res["seeds"], 4)
        # file partial bị TỪ CHỐI khi nạp vào bài
        with self.assertRaises(ResultsError):
            load_results(self.out.with_name("results.partial.json"))

    def test_time_budget_stops_cleanly(self):
        os.environ["FAIL_PROPOSED_SEED"] = "-1"
        self.assertEqual(self._run("--time-budget", "-1"), 2)             # hạn chót đã qua -> không chạy lần nào
        self.assertFalse(self.out.exists())

    def test_topic_mismatch_is_refused(self):
        os.environ["FAIL_PROPOSED_SEED"] = "-1"
        self.assertEqual(self._run(), 0)
        from src.tools.experiments import ResultsTopicMismatch
        self.assertIsNotNone(load_results(self.out, "  my   TOPIC "))    # khác hoa/thường/khoảng trắng vẫn khớp
        with self.assertRaises(ResultsTopicMismatch):
            load_results(self.out, "A Completely Different Topic")


class KaggleScriptTests(unittest.TestCase):
    def test_generated_entry_runs_end_to_end_and_metadata_is_sane(self):
        import run_on_kaggle as rk
        tmp = Path(tempfile.mkdtemp(prefix="kg_"))
        task = tmp / "task.py"
        task.write_text(TINY_TASK, encoding="utf-8")
        args = rk.argparse.Namespace(task=str(task), topic="My Topic", slug="my-topic", username="tester", seeds=3,
                                     quick=False, no_gpu=False, pip="", time_budget=None, resume_from=None,
                                     build_dir=str(tmp / "build"), dry_run=True)
        d = rk.build_kernel_dir(args)
        meta = _json.loads((d / "kernel-metadata.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["id"], "tester/my-topic")
        self.assertEqual(meta["code_file"], "kaggle_entry.py")
        self.assertEqual(meta["enable_gpu"], "true")
        self.assertEqual(meta["kernel_type"], "script")
        self.assertEqual(meta["is_private"], "true")
        work = tmp / "work"
        env = {**os.environ, "KAGGLE_WORKING_DIR": str(work), "FAIL_PROPOSED_SEED": "-1", "FLAG": str(tmp / "f")}
        r = _sp.run([sys.executable, str(d / "kaggle_entry.py")], env=env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        res = load_results(work / "results.json", "My Topic")
        self.assertEqual(res.seeds, 3)
        self.assertIn("MÃ THOÁT: 0", r.stdout)

    def test_bad_slug_and_dry_run(self):
        import run_on_kaggle as rk
        with self.assertRaises(SystemExit):
            rk.build_kernel_dir(rk.argparse.Namespace(task="x", topic="t", slug="Bad Slug!", username="u", seeds=3,
                                                      quick=False, no_gpu=False, pip="", time_budget=None,
                                                      resume_from=None, build_dir=None, dry_run=True))
