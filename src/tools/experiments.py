"""Phần THỰC NGHIỆM (Experiments) — trung thực với dữ liệu.

Hệ thống KHÔNG tự chạy thí nghiệm của bạn. Mọi con số kết quả trong bài chỉ có thể đến từ MỘT nguồn:
file `results.json` do chính bạn tạo (bằng `experiments/run_experiments.py` hoặc code của bạn).
  - Chưa có file: các bảng kết quả giữ nguyên khung với ô "--" (không in chữ TBD/Draft lên PDF);
    TODO.md liệt kê việc cần làm; lời văn viết ở thì tương lai và bị cấm nêu số.
  - Có file: bảng dựng từ ĐÚNG số liệu đó (mean ± std, in đậm giá trị tốt nhất, dấu † nếu có kiểm định),
    lời bình chỉ được dùng các số xuất hiện trong dữ liệu (câu chứa số lạ bị xoá tự động).

Định dạng results.json (mọi khoá ngoài datasets/metrics/methods đều tuỳ chọn):
{
  "datasets": ["MovieLens", "Pinterest"],
  "metrics": ["HR@10", "NDCG@10"],
  "higher_is_better": {"HR@10": true, "NDCG@10": true, "Latency (ms)": false},
  "seeds": 5,
  "methods": [
    {"name": "BPR", "scores": {"MovieLens": {"HR@10": {"mean": 0.69, "std": 0.003}, "NDCG@10": 0.41}}},
    {"name": "NeuMF", "proposed": true, "scores": {...}}
  ],
  "significance": [{"dataset": "MovieLens", "metric": "HR@10", "baseline": "BPR",
                    "test": "paired t-test", "p": 0.004}],
  "ablation": {"dataset": "MovieLens", "variants": [
      {"name": "Full model", "scores": {"HR@10": {"mean": 0.73, "std": 0.002}}},
      {"name": "w/o pre-training", "scores": {"HR@10": 0.70}}]},
  "sensitivity": {"parameter": "predictive factors", "dataset": "MovieLens", "metric": "HR@10",
                  "values": [8, 16, 32, 64],
                  "series": [{"name": "NeuMF", "values": [0.68, 0.71, 0.73, 0.73]}]},
  "dataset_stats": [{"name": "MovieLens", "fields": {"Interactions": 1000209, "Users": 6040}}],
  "setup": {"hardware": "1x RTX 3090", "epochs": 20, "dataset_urls": {"MovieLens": "http://..."}}
}
Một ô điểm có thể là số thường (0.91) hoặc {"mean":0.91,"std":0.004}.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from src.tools.latex_utils import latex_escape

MISSING = "--"
SIG_LEVEL = 0.05


class ResultsError(ValueError):
    """results.json sai định dạng (thông báo bằng tiếng Việt, chỉ rõ chỗ sai)."""


class ResultsTopicMismatch(ResultsError):
    """results.json thuộc về MỘT ĐỀ TÀI KHÁC với đề tài đang sinh bài."""


def _norm_topic(t: str) -> str:
    return re.sub(r"\s+", " ", str(t or "")).strip().lower()


def _cell(v) -> tuple[float, float | None] | None:
    """Số thường hoặc {"mean","std"} -> (mean, std)."""
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v), None
    if isinstance(v, dict) and isinstance(v.get("mean"), (int, float)):
        s = v.get("std")
        return float(v["mean"]), (float(s) if isinstance(s, (int, float)) else None)
    return None


@dataclass
class ExperimentResults:
    datasets: list[str]
    metrics: list[str]
    methods: list[dict]
    higher_is_better: dict[str, bool] = field(default_factory=dict)
    setup: dict = field(default_factory=dict)
    significance: list[dict] = field(default_factory=list)
    ablation: dict | None = None
    sensitivity: dict | None = None
    dataset_stats: list[dict] = field(default_factory=list)
    seeds: int | None = None
    topic: str | None = None
    raw: dict = field(default_factory=dict)

    def stat(self, method: dict, dataset: str, metric: str):
        return _cell(((method.get("scores") or {}).get(dataset) or {}).get(metric))

    def value(self, method: dict, dataset: str, metric: str) -> float | None:
        c = self.stat(method, dataset, metric)
        return c[0] if c else None

    def better(self, metric: str) -> bool:
        return self.higher_is_better.get(metric, True)

    def has_ablation(self) -> bool:
        return bool(self.ablation and self.ablation.get("variants"))

    def has_sensitivity(self) -> bool:
        s = self.sensitivity
        return bool(s and s.get("values") and s.get("series"))


def _check(cond: bool, msg: str) -> None:
    if not cond:
        raise ResultsError(msg)


def load_results(path: str | Path | None, topic: str | None = None) -> ExperimentResults | None:
    """Đọc results.json. None nếu file không tồn tại; ResultsError (tiếng Việt) nếu sai định dạng.
    Nếu truyền `topic` và file có ghi đề tài khác -> ResultsTopicMismatch (không để số của đề tài này lọt vào bài khác)."""
    if not path:
        return None
    p = Path(path)
    if not p.exists():
        return None
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ResultsError(f"{p}: không phải JSON hợp lệ ({e}).") from e
    if (raw.get("_demo") or raw.get("_quick") or raw.get("_example")) and os.environ.get("ALLOW_DEMO_RESULTS") != "1":
        raise ResultsError(
            f"{p}: đây là kết quả DEMO/--quick/MẪU (chỉ để kiểm tra đường ống hoặc minh hoạ định dạng), KHÔNG phải kết quả thật nên bị từ chối. "
            "Hãy chạy thí nghiệm thật không có --quick/--demo (xem experiments/README.md).")
    if raw.get("_partial"):
        raise ResultsError(f"{p}: đây là file CHƯA ĐỦ lần chạy (partial) — hãy chạy lại run_experiments.py cho đủ.")
    if topic and raw.get("topic") and _norm_topic(raw["topic"]) != _norm_topic(topic):
        raise ResultsTopicMismatch(
            f"{p}: kết quả này thuộc đề tài “{raw['topic']}”, không khớp đề tài đang viết “{topic}”. "
            "Dùng thư mục riêng cho mỗi đề tài (topics/<tên>/) hoặc chạy lại thí nghiệm cho đề tài này.")
    for k in ("datasets", "metrics", "methods"):
        _check(isinstance(raw.get(k), list) and raw[k], f"{p}: thiếu khoá '{k}' (phải là danh sách không rỗng).")
    for m in raw["methods"]:
        _check(isinstance(m, dict) and m.get("name"), f"{p}: mỗi phần tử trong 'methods' cần có 'name'.")
        for ds, mets in (m.get("scores") or {}).items():
            _check(ds in raw["datasets"], f"{p}: phương pháp '{m['name']}' có dataset '{ds}' không nằm trong 'datasets'.")
            for met, v in (mets or {}).items():
                _check(met in raw["metrics"], f"{p}: metric '{met}' của '{m['name']}' không nằm trong 'metrics'.")
                _check(_cell(v) is not None, f"{p}: giá trị {m['name']}/{ds}/{met} phải là số hoặc {{\"mean\":..,\"std\":..}}, nhận '{v}'.")
    names = {str(m["name"]) for m in raw["methods"]}
    for s in raw.get("significance") or []:
        _check(isinstance(s.get("p"), (int, float)), f"{p}: mỗi mục 'significance' cần có 'p' là số.")
        _check(s.get("dataset") in raw["datasets"] and s.get("metric") in raw["metrics"],
               f"{p}: 'significance' tham chiếu dataset/metric không có trong danh sách.")
        _check(str(s.get("baseline")) in names, f"{p}: 'significance' có baseline '{s.get('baseline')}' không nằm trong 'methods'.")
    ab = raw.get("ablation")
    if ab:
        _check(isinstance(ab.get("variants"), list) and ab["variants"], f"{p}: 'ablation.variants' phải là danh sách không rỗng.")
        for v in ab["variants"]:
            _check(v.get("name"), f"{p}: mỗi variant trong 'ablation' cần có 'name'.")
            for met, val in (v.get("scores") or {}).items():
                _check(_cell(val) is not None, f"{p}: giá trị ablation '{v['name']}'/{met} phải là số hoặc mean/std.")
    se = raw.get("sensitivity")
    if se:
        n = len(se.get("values") or [])
        _check(n > 0 and se.get("series"), f"{p}: 'sensitivity' cần 'values' và 'series'.")
        for s in se["series"]:
            _check(len(s.get("values") or []) == n, f"{p}: chuỗi '{s.get('name')}' trong 'sensitivity' phải có đúng {n} giá trị.")
    return ExperimentResults(
        datasets=[str(x) for x in raw["datasets"]], metrics=[str(x) for x in raw["metrics"]],
        methods=raw["methods"], higher_is_better=raw.get("higher_is_better") or {},
        setup=raw.get("setup") or {}, significance=raw.get("significance") or [],
        ablation=ab or None, sensitivity=se or None, dataset_stats=raw.get("dataset_stats") or [],
        seeds=raw.get("seeds") if isinstance(raw.get("seeds"), int) else None,
        topic=raw.get("topic"), raw=raw,
    )


# ----------------------------------------------------------------------------- định dạng ô
def _fmt(v: float) -> str:
    if float(v).is_integer() and abs(v) >= 100:
        return f"{int(v):,}".replace(",", ",")
    return f"{v:.3f}" if abs(v) < 10 else f"{v:.1f}"


def _fmt_cell(c: tuple[float, float | None]) -> str:
    return _fmt(c[0]) if c[1] is None else f"{_fmt(c[0])} ± {_fmt(c[1])}"


Grid = tuple[list[str], list[list[tuple[str, bool]]]]   # header, rows[[(text, bold)]]


def _significant(res: ExperimentResults, method: dict, dataset: str, metric: str) -> bool:
    """Phương pháp đề xuất có khác biệt có ý nghĩa (p < 0.05) so với MỌI baseline đã kiểm định không?"""
    if not method.get("proposed"):
        return False
    rows = [s for s in res.significance if s["dataset"] == dataset and s["metric"] == metric]
    return bool(rows) and all(float(s["p"]) < SIG_LEVEL for s in rows)


def performance_grid(res: ExperimentResults) -> tuple[Grid, bool]:
    """Bảng so sánh hiệu năng. Trả về (grid, có_dấu_dagger). Cột = (dataset, metric)."""
    cols = [(d, m) for d in res.datasets for m in res.metrics
            if any(res.stat(x, d, m) for x in res.methods)]
    best: dict[tuple[str, str], float] = {}
    for d, m in cols:
        vals = [res.value(x, d, m) for x in res.methods if res.value(x, d, m) is not None]
        best[(d, m)] = max(vals) if res.better(m) else min(vals)
    header = ["Method"] + [f"{d} {m}" if len(res.datasets) > 1 else m for d, m in cols]
    daggers = False
    rows = []
    for x in res.methods:
        row = [(str(x["name"]), bool(x.get("proposed")))]
        for d, m in cols:
            c = res.stat(x, d, m)
            if c is None:
                row.append((MISSING, False))
                continue
            txt = _fmt_cell(c)
            if _significant(res, x, d, m):
                txt += "†"
                daggers = True
            row.append((txt, c[0] == best[(d, m)]))
        rows.append(row)
    return (header, rows), daggers


def placeholder_grid(eval_rows: list[dict]) -> Grid:
    """Chưa có số liệu: giữ khung bảng (baseline × metric) với ô '--' — KHÔNG in chữ TBD."""
    metrics: list[str] = []
    baselines: list[str] = []
    for r in eval_rows or []:
        for m in re.split(r"\s*[,;/&]\s*|\s+and\s+", str(r.get("metric", ""))):
            m = m.strip()
            if m and m not in metrics:
                metrics.append(m[:24])
        b = str(r.get("baseline", "")).strip()
        if b and b not in baselines:
            baselines.append(b[:40])
    metrics = metrics[:4] or ["Metric 1", "Metric 2"]
    baselines = baselines[:4] or ["Baseline 1", "Baseline 2"]
    names = baselines + ["Proposed"]
    return ["Method"] + metrics, [[(n, n == "Proposed")] + [(MISSING, False)] * len(metrics) for n in names]


def count_missing(grid: Grid) -> int:
    return sum(1 for r in grid[1] for c in r[1:] if c[0] == MISSING)


def ablation_grid(res: ExperimentResults) -> Grid | None:
    if not res.has_ablation():
        return None
    variants = res.ablation["variants"]
    mets = [m for m in res.metrics if any(m in (v.get("scores") or {}) for v in variants)]
    best = {}
    for m in mets:
        vals = [c[0] for v in variants if (c := _cell((v.get("scores") or {}).get(m)))]
        best[m] = max(vals) if res.better(m) else min(vals)
    rows = []
    for v in variants:
        row = [(str(v["name"]), False)]
        for m in mets:
            c = _cell((v.get("scores") or {}).get(m))
            row.append((MISSING, False) if c is None else (_fmt_cell(c), c[0] == best[m]))
        rows.append(row)
    return ["Variant"] + mets, rows


def stats_grid(res: ExperimentResults) -> Grid | None:
    """Bảng thống kê dữ liệu (như Table 1 của bài mẫu) từ 'dataset_stats'."""
    if not res.dataset_stats:
        return None
    fields: list[str] = []
    for d in res.dataset_stats:
        for k in (d.get("fields") or {}):
            if k not in fields:
                fields.append(k)
    rows = []
    for d in res.dataset_stats:
        row = [(str(d["name"]), False)]
        for k in fields:
            v = (d.get("fields") or {}).get(k)
            row.append((MISSING, False) if v is None else (_fmt(v) if isinstance(v, (int, float)) else str(v), False))
        rows.append(row)
    return ["Dataset"] + fields, rows


def sensitivity_data(res: ExperimentResults):
    """-> (parameter, values, [(name, [y])], metric) hoặc None."""
    if not res.has_sensitivity():
        return None
    s = res.sensitivity
    return (str(s.get("parameter", "parameter")), list(s["values"]),
            [(str(x.get("name", "")), list(x["values"])) for x in s["series"]], str(s.get("metric", "")))


# ----------------------------------------------------------------------------- LaTeX
def _cell_tex(text: str, bold: bool) -> str:
    if text == MISSING:
        return "--"
    dag = text.endswith("†")
    core = text[:-1] if dag else text
    t = r" $\pm$ ".join(latex_escape(part.strip()) for part in core.split("±"))
    t = f"\\textbf{{{t}}}" if bold else t
    return t + (r"$^{\dagger}$" if dag else "")


def grid_table_tex(grid: Grid, caption: str, label: str, wide: bool | None = None, note: str = "") -> str:
    """Bảng kiểu bài mẫu: caption PHÍA TRÊN ('Table n: ...'), kẻ ngang booktabs, giá trị tốt nhất in đậm."""
    header, rows = grid
    ncol = len(header)
    wide = ncol > 4 if wide is None else wide
    env = "table*" if wide else "table"
    width = "\\textwidth" if wide else "\\columnwidth"
    colspec = "l" + "c" * (ncol - 1)
    head = " & ".join(f"\\textbf{{{latex_escape(h)}}}" for h in header) + r" \\"
    body = "\n".join(" & ".join(_cell_tex(t, b) for t, b in r) + r" \\" for r in rows)
    foot = f"\n\\par\\vspace{{2pt}}{{\\footnotesize {note}}}" if note else ""
    return (
        f"\\begin{{{env}}}[!t]\n\\centering\\small\n\\caption{{{caption}}}\n\\label{{{label}}}\n"
        f"\\adjustbox{{max width={width}}}{{%\n\\begin{{tabular}}{{{colspec}}}\n\\toprule\n{head}\n\\midrule\n{body}\n"
        f"\\bottomrule\n\\end{{tabular}}}}{foot}\n\\end{{{env}}}\n"
    )


# ----------------------------------------------------------------------------- lưới chắn số liệu
def _numbers_in(obj) -> list[float]:
    out: list[float] = []
    if isinstance(obj, bool):
        return out
    if isinstance(obj, (int, float)):
        out.append(float(obj))
    elif isinstance(obj, dict):
        for v in obj.values():
            out += _numbers_in(v)
    elif isinstance(obj, list):
        for v in obj:
            out += _numbers_in(v)
    return out


def allowed_numbers(res: ExperimentResults | None) -> set[str]:
    """Mọi biểu diễn chấp nhận được của số liệu THẬT (và chênh lệch/tỷ lệ tính từ chúng)."""
    allowed: set[str] = set()
    if res is None:
        return allowed

    def add(v: float) -> None:
        forms = {f"{v:g}", f"{v:.1f}", f"{v:.2f}", f"{v:.3f}", f"{v:.4f}", f"{v * 100:.1f}",
                 f"{v * 100:.2f}", f"{v * 100:.0f}", f"{v:,.0f}", f"{v:,.1f}"}
        for s in forms:
            allowed.add(s)
            if s.startswith("0."):
                allowed.add(s[1:])
            allowed.add(s.replace(",", ""))

    for v in _numbers_in(res.raw):
        add(v)
    allowed |= {"0.05", "0.01", "0.001", "5", "1"}
    for d in res.datasets:
        for met in res.metrics:
            vs = [v for x in res.methods if (v := res.value(x, d, met)) is not None]
            for a in vs:
                for b in vs:
                    add(abs(a - b))
                    if b:
                        add(abs(a - b) / abs(b))
    return allowed


_NUM_RE = re.compile(r"(?<![\w.\\])(\d+(?:[.,]\d+)*)(\s?%)?(?![\w])")


def strip_unsupported_numbers(text: str, allowed: set[str]) -> tuple[str, list[str]]:
    """Xoá mọi câu chứa số 'kiểu kết quả' (thập phân, ≥ 21, hoặc có %) không có trong dữ liệu thật.
    Bỏ qua: số nguyên nhỏ (≤ 20), năm (1900–2100), RQ1/H2/Table 3/Figure 2/Section 4/Eq., công thức, \\cite."""
    if not text.strip():
        return text, []
    shield: list[str] = []

    def hold(m: re.Match) -> str:
        shield.append(m.group(0))
        return f"\x00{len(shield) - 1}\x00"

    work = re.sub(r"@@M\d+@@|\$[^$\n]+\$|\\(?:cite|ref|eqref|label|url|footnote)[a-z]*\{[^}]*\}", hold, text)
    removed: list[str] = []
    kept_lines = []
    for line in work.split("\n"):
        sents = re.split(r"(?<=[.!?])\s+", line)
        keep = []
        for s in sents:
            bad = False
            for m in _NUM_RE.finditer(s):
                tok = m.group(1)
                tok_plain = tok.replace(",", "")
                pct = bool(m.group(2))
                ctx = s[max(0, m.start() - 9): m.start()].lower()
                if re.search(r"(rq|h|table|tab\.|fig\.|figure|section|sec\.|eq\.|\()\s*~?\s*$", ctx):
                    continue
                if re.fullmatch(r"\d+", tok_plain) and not pct and "," not in tok:
                    n = int(tok_plain)
                    if n <= 20 or 1900 <= n <= 2100:
                        continue
                variants = {tok, tok_plain, tok.replace(",", "."), tok_plain.lstrip("0")}
                if variants & allowed:
                    continue
                bad = True
                break
            if bad:
                removed.append(re.sub(r"\x00(\d+)\x00", lambda mm: shield[int(mm.group(1))], s)[:120])
            else:
                keep.append(s)
        kept_lines.append(" ".join(keep))
    out = "\n".join(kept_lines)
    out = re.sub(r"\x00(\d+)\x00", lambda m: shield[int(m.group(1))], out)
    return out, removed


def summarize_for_prompt(res: ExperimentResults) -> str:
    """Số liệu THẬT dạng text để đưa vào prompt (LLM chỉ được nói về những số này)."""
    (header, rows), _ = performance_grid(res)
    lines = ["PERFORMANCE (mean ± std; † = significant):", " | ".join(header)]
    for r in rows:
        lines.append(" | ".join(t + (" (best)" if b and t[:1].isdigit() else "") for t, b in r))
    if res.significance:
        lines.append("SIGNIFICANCE TESTS:")
        lines += [f"- {s['dataset']}/{s['metric']}: proposed vs {s['baseline']}, {s.get('test', 'test')}, p={s['p']}"
                  for s in res.significance]
    ab = ablation_grid(res)
    if ab:
        lines += ["ABLATION (" + str((res.ablation or {}).get("dataset", "")) + "):", " | ".join(ab[0])]
        lines += [" | ".join(t for t, _ in r) for r in ab[1]]
    sd = sensitivity_data(res)
    if sd:
        param, values, series, metric = sd
        lines.append(f"SENSITIVITY of {metric} w.r.t. {param} = {values}:")
        lines += [f"- {n}: {ys}" for n, ys in series]
    if res.seeds:
        lines.append(f"Seeds: {res.seeds}")
    if res.setup:
        lines.append(f"Setup facts: {res.setup}")
    return "\n".join(lines)
