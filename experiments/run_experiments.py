#!/usr/bin/env python3
"""Chạy thí nghiệm THẬT nhiều seed và xuất `results.json` cho bài báo.

    python experiments/run_experiments.py --demo --quick            # kiểm tra đường ống (dữ liệu sklearn có sẵn)
    python experiments/run_experiments.py --task my_task.py --seeds 5 --out results.json

Runner lo phần "máy móc" để số liệu luôn nhất quán và có thể tái lập:
  - lặp qua dataset x phương pháp x seed, ghi log từng lần chạy;
  - gộp thành mean ± std (ddof=1), kiểm định t ghép cặp (paired t-test, scipy) giữa phương pháp đề xuất
    và TỪNG baseline trên các seed;
  - ablation (bỏ từng thành phần) và độ nhạy theo siêu tham số;
  - ghi `results.json` (đúng schema của hệ thống) và `results_raw.csv` (từng seed).
Chịu được việc Kaggle/Colab ngắt phiên: mỗi lần chạy (dataset, phương pháp, seed) được ghi NGAY vào
`<out>.runs.jsonl`; chạy lại cùng lệnh thì bỏ qua các lần đã xong. `results.json` chỉ được ghi khi ĐỦ mọi lần chạy;
nếu thiếu (lỗi, hết giờ `--time-budget`) thì ghi `<out>.partial.json` + danh sách lần còn thiếu và KHÔNG tạo
results.json (tránh lấy một phần số liệu). Kết quả mang `topic` và `task_sha256` để bài báo từ chối nếu sai đề tài.
KHÔNG có bước nào "làm đẹp" số: số trong bảng = số chạy ra. File demo luôn ghi ra `results.demo.json`
và bị hệ thống từ chối nạp vào bài báo thật (xem README).

Viết task của bạn: một file Python định nghĩa `get_task(quick: bool) -> dict` (xem `demo_task()` bên dưới):
    {
      "datasets": {"Tên": loader},        # loader(seed) -> data tuỳ ý (ví dụ dict X_train, y_train, X_test, y_test)
      "metrics":  ["Accuracy", "F1"],     # tên các độ đo mà phương pháp trả về
      "higher_is_better": {"Latency (ms)": False},          # tuỳ chọn, mặc định True
      "methods":  [{"name": "Baseline", "run": fn, "proposed": False}, ...],   # fn(data, seed) -> {metric: float}
      "ablation": {"dataset": "Tên", "variants": [{"name": "Full", "run": fn}, ...]},            # tuỳ chọn
      "sensitivity": {"parameter": "k", "dataset": "Tên", "metric": "Accuracy",
                      "values": [1, 2, 4], "series": [{"name": "Proposed", "run": fn_with_value}]},  # fn(data, seed, value) -> {metric: float}
      "dataset_stats": {"Tên": {"Samples": 1000}},          # tuỳ chọn (hoặc hàm của data trong "stats_fn")
      "setup": {"hardware": "...", "dataset_urls": {"Tên": "https://..."}},   # tuỳ chọn, chỉ ghi SỰ THẬT
    }
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import logging
import platform
import statistics as st
import sys
import time
from pathlib import Path

log = logging.getLogger("experiments")


# --------------------------------------------------------------------------- thống kê
def mean_std(xs: list[float]) -> dict:
    m = float(sum(xs) / len(xs))
    return {"mean": m, "std": float(st.stdev(xs)) if len(xs) > 1 else 0.0}


def paired_ttest(a: list[float], b: list[float]) -> float | None:
    """p-value của paired t-test (hai phía). None nếu < 2 seed hoặc không tính được."""
    if len(a) < 2 or len(a) != len(b):
        return None
    try:
        from scipy import stats
        diff = [x - y for x, y in zip(a, b)]
        if all(abs(d) < 1e-15 for d in diff):
            return 1.0
        return float(stats.ttest_rel(a, b).pvalue)
    except Exception as e:  # noqa: BLE001
        log.warning("Không tính được t-test: %s", e)
        return None


# --------------------------------------------------------------------------- lưu từng lần chạy
class RunStore:
    """Nhật ký JSONL: mỗi dòng = một lần chạy đã xong. Ghi ngay (flush) để phiên bị ngắt cũng không mất."""

    def __init__(self, path: Path | None):
        self.path = path
        self.done: dict[str, dict] = {}
        if path and path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                try:
                    rec = json.loads(line)
                    self.done[rec["key"]] = rec["out"]
                except Exception:  # noqa: BLE001 — dòng cuối có thể dở dang khi bị ngắt
                    continue

    def put(self, key: str, out: dict) -> None:
        self.done[key] = out
        if self.path:
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"key": key, "out": out}, ensure_ascii=False) + "\n")
                f.flush()


class Runner:
    """Thực thi từng lần chạy có cache, giới hạn thời gian và ghi nhận lần chạy còn thiếu."""

    def __init__(self, store: RunStore, budget_s: float | None, progress):
        self.store, self.progress = store, progress
        self.deadline = time.time() + budget_s if budget_s else None
        self.missing: list[str] = []

    def run(self, key: str, label: str, fn):
        if key in self.store.done:
            self.progress(f"(đã có) {label}")
            return self.store.done[key]
        if self.deadline and time.time() > self.deadline:
            self.missing.append(f"{label} [hết giờ --time-budget]")
            return None
        t0 = time.time()
        try:
            out = fn()
        except Exception as e:  # noqa: BLE001 — KHÔNG nuốt lỗi: ghi nhận là thiếu, kết quả sẽ không đầy đủ
            self.missing.append(f"{label} [lỗi: {type(e).__name__}: {e}]")
            log.error("Lỗi %s: %s", label, e)
            return None
        out = {k: float(v) for k, v in out.items()}
        self.store.put(key, out)
        self.progress(f"{label}: " + ", ".join(f"{k}={v:.4f}" for k, v in out.items()) + f" ({time.time() - t0:.1f}s)")
        return out


# --------------------------------------------------------------------------- vòng chạy
def run_task(task: dict, seeds: list[int], progress=print, store: RunStore | None = None,
             budget_s: float | None = None) -> tuple[dict | None, list[dict], list[str]]:
    """Chạy toàn bộ task -> (results | None nếu còn thiếu, các dòng raw, danh sách lần chạy còn thiếu)."""
    metrics = list(task["metrics"])
    hib = dict(task.get("higher_is_better") or {})
    rn = Runner(store or RunStore(None), budget_s, progress)
    raw_rows: list[dict] = []
    data_cache: dict[tuple[str, int], object] = {}

    def data_of(ds: str, seed: int):
        if (ds, seed) not in data_cache:
            data_cache[(ds, seed)] = task["datasets"][ds](seed)
        return data_cache[(ds, seed)]

    per_run: dict[tuple[str, str, str], list[float]] = {}     # (method, dataset, metric) -> [giá trị theo seed]
    for ds in task["datasets"]:
        for m in task["methods"]:
            for seed in seeds:
                out = rn.run(f"main|{m['name']}|{ds}|{seed}", f"[{ds}] {m['name']} seed={seed}",
                             lambda m=m, ds=ds, seed=seed: m["run"](data_of(ds, seed), seed))
                if out is None:
                    continue
                for met in metrics:
                    if met in out:
                        per_run.setdefault((m["name"], ds, met), []).append(out[met])
                        raw_rows.append({"part": "main", "method": m["name"], "dataset": ds, "metric": met,
                                         "seed": seed, "value": out[met]})

    ab_out, se_out = None, None
    ab = task.get("ablation")
    if ab:
        ds = ab["dataset"]
        variants = []
        for v in ab["variants"]:
            vals: dict[str, list[float]] = {}
            for seed in seeds:
                out = rn.run(f"ablation|{v['name']}|{ds}|{seed}", f"[ablation/{ds}] {v['name']} seed={seed}",
                             lambda v=v, ds=ds, seed=seed: v["run"](data_of(ds, seed), seed))
                if out is None:
                    continue
                for met in metrics:
                    if met in out:
                        vals.setdefault(met, []).append(out[met])
                        raw_rows.append({"part": "ablation", "method": v["name"], "dataset": ds, "metric": met,
                                         "seed": seed, "value": out[met]})
            variants.append({"name": v["name"], "scores": {k: mean_std(x) for k, x in vals.items()}})
        ab_out = {"dataset": ds, "variants": variants}

    se = task.get("sensitivity")
    if se:
        ds, metric = se["dataset"], se["metric"]
        series = []
        for s_ in se["series"]:
            ys = []
            for val in se["values"]:
                xs = []
                for seed in seeds:
                    out = rn.run(f"sens|{s_['name']}|{val}|{ds}|{seed}",
                                 f"[sensitivity/{ds}] {s_['name']} {se['parameter']}={val} seed={seed}",
                                 lambda s_=s_, val=val, ds=ds, seed=seed: s_["run"](data_of(ds, seed), seed, val))
                    if out is None or metric not in out:
                        continue
                    xs.append(out[metric])
                    raw_rows.append({"part": "sensitivity", "method": f"{s_['name']}@{val}", "dataset": ds,
                                     "metric": metric, "seed": seed, "value": out[metric]})
                ys.append(float(sum(xs) / len(xs)) if xs else float("nan"))
            series.append({"name": s_["name"], "values": ys})
        se_out = {"parameter": se["parameter"], "dataset": ds, "metric": metric,
                  "values": list(se["values"]), "series": series}

    if rn.missing:
        return None, raw_rows, rn.missing

    methods_out = []
    for m in task["methods"]:
        scores: dict = {}
        for ds in task["datasets"]:
            scores[ds] = {met: mean_std(per_run[(m["name"], ds, met)])
                          for met in metrics if (m["name"], ds, met) in per_run}
        methods_out.append({"name": m["name"], "proposed": bool(m.get("proposed")), "scores": scores})

    significance = []
    for pm in (m for m in task["methods"] if m.get("proposed")):
        for bm in task["methods"]:
            if bm is pm or bm.get("proposed"):
                continue
            for ds in task["datasets"]:
                for met in metrics:
                    a_, b_ = per_run.get((pm["name"], ds, met)), per_run.get((bm["name"], ds, met))
                    p = paired_ttest(a_, b_) if a_ and b_ else None
                    if p is not None:
                        significance.append({"dataset": ds, "metric": met, "baseline": bm["name"],
                                             "test": "paired t-test", "p": p})

    results: dict = {"datasets": list(task["datasets"]), "metrics": metrics, "higher_is_better": hib,
                     "seeds": len(seeds), "methods": methods_out, "significance": significance}
    if ab_out:
        results["ablation"] = ab_out
    if se_out:
        results["sensitivity"] = se_out
    stats_in = task.get("dataset_stats") or {}
    if stats_in:
        results["dataset_stats"] = [{"name": n, "fields": f} for n, f in stats_in.items()]
    setup = dict(task.get("setup") or {})
    setup.setdefault("python", platform.python_version())
    setup.setdefault("platform", platform.platform())
    results["setup"] = setup
    return results, raw_rows, []


# --------------------------------------------------------------------------- demo (offline)
def demo_task(quick: bool) -> dict:
    """Pipeline-check trên dữ liệu có sẵn trong scikit-learn. KHÔNG liên quan đề tài của bạn."""
    from sklearn import datasets as skd
    from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import accuracy_score, f1_score
    from sklearn.model_selection import train_test_split
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    def loader(fn):
        def load(seed):
            X, y = fn(return_X_y=True)
            if quick:
                X, y = X[:400], y[:400]
            return train_test_split(X, y, test_size=0.3, random_state=seed, stratify=y)
        return load

    def scores(model):
        def run(data, seed):
            Xtr, Xte, ytr, yte = data
            model.set_params(**{k: seed for k in model.get_params() if k.endswith("random_state")})
            pred = model.fit(Xtr, ytr).predict(Xte)
            return {"Accuracy": accuracy_score(yte, pred), "Macro-F1": f1_score(yte, pred, average="macro")}
        return run

    def gb(n):
        def run(data, seed, value=None):
            return scores(GradientBoostingClassifier(n_estimators=value or n, random_state=seed))(data, seed)
        return run

    n_trees = 20 if quick else 100
    return {
        "datasets": {"Digits": loader(skd.load_digits), "BreastCancer": loader(skd.load_breast_cancer)},
        "metrics": ["Accuracy", "Macro-F1"],
        "methods": [
            {"name": "LogReg (baseline)", "run": scores(make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000)))},
            {"name": "RandomForest (baseline)", "run": scores(RandomForestClassifier(n_estimators=n_trees, random_state=0))},
            {"name": "GradBoost (demo 'proposed')", "proposed": True, "run": gb(n_trees)},
        ],
        "ablation": {"dataset": "Digits", "variants": [
            {"name": "GradBoost (full)", "run": gb(n_trees)},
            {"name": "w/ 5 trees", "run": gb(5)},
        ]},
        "sensitivity": {"parameter": "number of trees", "dataset": "Digits", "metric": "Accuracy",
                        "values": [5, 10, 20] if quick else [10, 50, 100, 200],
                        "series": [{"name": "GradBoost", "run": gb(n_trees)}]},
        "dataset_stats": {"Digits": {"Samples": 1797, "Features": 64}, "BreastCancer": {"Samples": 569, "Features": 30}},
        "setup": {"note": "DEMO: dữ liệu sklearn có sẵn, chỉ để kiểm tra đường ống"},
    }


def load_task_file(path: str, quick: bool) -> dict:
    spec = importlib.util.spec_from_file_location("user_task", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if not hasattr(mod, "get_task"):
        raise SystemExit(f"{path} phải định nghĩa hàm get_task(quick: bool) -> dict")
    return mod.get_task(quick)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--task", help="file Python định nghĩa get_task(quick)")
    ap.add_argument("--demo", action="store_true", help="chạy bài kiểm tra offline (ghi results.demo.json)")
    ap.add_argument("--quick", action="store_true", help="lấy mẫu con + ít seed để thử nhanh")
    ap.add_argument("--seeds", type=int, default=5, help="số seed (khuyến nghị >= 3, tốt nhất 5)")
    ap.add_argument("--out", default=None, help="đường dẫn results.json")
    ap.add_argument("--topic", default=None, help="tên đề tài, ghi vào results.json (bài báo sẽ đối chiếu)")
    ap.add_argument("--time-budget", type=float, default=None,
                    help="phút; hết giờ thì dừng bắt đầu lần chạy mới, lưu phần đã xong để chạy tiếp lần sau")
    ap.add_argument("--fresh", action="store_true", help="xoá nhật ký .runs.jsonl và chạy lại từ đầu")
    args = ap.parse_args(argv)
    if not args.task and not args.demo:
        ap.error("cần --task <file.py> hoặc --demo")

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    seeds = list(range(2 if args.quick else args.seeds))
    task = demo_task(args.quick) if args.demo else load_task_file(args.task, args.quick)
    out = Path(args.out or ("results.demo.json" if args.demo else "results.json"))
    if args.demo and out.name == "results.json":
        raise SystemExit("Kết quả DEMO không được ghi vào results.json (sẽ bị nhầm là kết quả thật).")
    if not args.demo and not args.topic:
        log.warning("Không có --topic: results.json sẽ KHÔNG ghi tên đề tài, bài báo không đối chiếu được.")

    log_path = out.with_name(out.stem + ".runs.jsonl")
    if args.fresh and log_path.exists():
        log_path.unlink()
    store = RunStore(log_path)
    if store.done:
        log.info("Tìm thấy %d lần chạy đã xong trong %s — sẽ bỏ qua chúng.", len(store.done), log_path)

    results, raw, missing = run_task(task, seeds, progress=log.info, store=store,
                                     budget_s=args.time_budget * 60 if args.time_budget else None)
    raw_path = out.with_name(out.stem + "_raw.csv")
    with raw_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["part", "method", "dataset", "metric", "seed", "value"])
        w.writeheader()
        w.writerows(raw)

    if missing:
        partial = out.with_name(out.stem + ".partial.json")
        partial.write_text(json.dumps({"_partial": True, "missing": missing}, ensure_ascii=False, indent=2),
                           encoding="utf-8")
        log.error("CHƯA ĐỦ: còn %d lần chạy. KHÔNG tạo %s. Chạy lại cùng lệnh để tiếp tục.", len(missing), out)
        for m_ in missing[:20]:
            log.error("  thiếu: %s", m_)
        return 2

    if args.topic:
        results["topic"] = args.topic
    if args.task:
        results["task_sha256"] = hashlib.sha256(Path(args.task).read_bytes()).hexdigest()
    if args.demo:
        results["_demo"] = True
    if args.quick:
        results["_quick"] = True
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("Đã ghi %s và %s (%d lần chạy, %d seed).", out, raw_path, len(raw), len(seeds))
    if args.quick:
        log.warning("Chế độ --quick: chỉ để thử nhanh, KHÔNG dùng cho bài báo. File mang cờ _quick.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
