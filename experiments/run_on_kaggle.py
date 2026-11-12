#!/usr/bin/env python3
"""Đẩy thí nghiệm của một đề tài lên Kaggle (GPU miễn phí) từ máy bạn, đợi chạy, tải results.json về.

    python experiments/run_on_kaggle.py push   --task topics/x/task.py --topic "Tên đề tài" --slug x [--quick]
    python experiments/run_on_kaggle.py status --slug x
    python experiments/run_on_kaggle.py output --slug x --dest topics/x --topic "Tên đề tài"

Cần: `pip install kaggle` và token API (Kaggle -> Settings -> API -> Create New Token -> ~/.kaggle/kaggle.json).
Máy bạn KHÔNG chạy thí nghiệm: nó chỉ đóng gói và gửi đi. Thí nghiệm không dùng khoá API của mô hình ngôn ngữ
nên không có khoá bí mật nào được đưa lên Kaggle (đừng thêm khoá vào task.py).

Cách hoạt động: runner + task.py được nhúng (base64) vào MỘT file script `kaggle_entry.py` — vì `kaggle kernels push`
chỉ gửi một file mã. Trên Kaggle, script ghi lại hai file đó, chạy run_experiments.py và để results.json ở
/kaggle/working (thư mục Output). CHƯA được kiểm tra với Kaggle thật: lần chạy đầu tiên của bạn là lần thử thật,
hãy bắt đầu bằng `--quick`.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
RUNNER = HERE / "run_experiments.py"
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,49}$")

ENTRY_TEMPLATE = '''# FILE SINH TỰ ĐỘNG bởi experiments/run_on_kaggle.py — không sửa tay.
import base64, os, shutil, subprocess, sys

PIP = {pip!r}
TOPIC = {topic!r}
SEEDS = {seeds!r}
QUICK = {quick!r}
TIME_BUDGET = {budget!r}
RESUME_SLUG = {resume!r}
RUNNER_B64 = "{runner}"
TASK_B64 = "{task}"

work = os.environ.get("KAGGLE_WORKING_DIR") or ("/kaggle/working" if os.path.isdir("/kaggle/working") else os.getcwd())
os.makedirs(work, exist_ok=True)
if PIP:
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", *PIP], check=False)
for name, blob in (("run_experiments.py", RUNNER_B64), ("task.py", TASK_B64)):
    with open(os.path.join(work, name), "wb") as f:
        f.write(base64.b64decode(blob))
if RESUME_SLUG:  # nối tiếp nhật ký từ lần chạy trước (kernel_sources gắn Output của lần trước vào /kaggle/input)
    prev = os.path.join("/kaggle/input", RESUME_SLUG, "results.runs.jsonl")
    if os.path.exists(prev):
        shutil.copy(prev, os.path.join(work, "results.runs.jsonl"))
        print("Đã nạp nhật ký lần chạy trước:", prev)
sys.path.insert(0, work)
import run_experiments as rx
args = ["--task", os.path.join(work, "task.py"), "--out", os.path.join(work, "results.json"),
        "--topic", TOPIC, "--seeds", str(SEEDS)]
if QUICK:
    args.append("--quick")
if TIME_BUDGET:
    args += ["--time-budget", str(TIME_BUDGET)]
rc = rx.main(args)
sys.stdout.buffer.write((f"MÃ THOÁT: {{rc}} (0 = đủ kết quả; 2 = còn thiếu lần chạy, xem results.partial.json)").encode("utf-8"))
'''


def b64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("ascii")


def build_entry(task: Path, topic: str, seeds: int, quick: bool, pip: list[str] | None = None,
                time_budget: float | None = None, resume_slug: str | None = None) -> str:
    if not task.exists():
        raise SystemExit(f"Không thấy file task: {task}")
    return ENTRY_TEMPLATE.format(pip=pip or [], topic=topic, seeds=seeds, quick=quick, budget=time_budget,
                                 resume=resume_slug, runner=b64(RUNNER), task=b64(task))


def kaggle_username(arg: str | None) -> str:
    u = arg or os.environ.get("KAGGLE_USERNAME")
    if not u:
        cred = Path.home() / ".kaggle" / "kaggle.json"
        if cred.exists():
            u = json.loads(cred.read_text(encoding="utf-8")).get("username")
    if not u:
        raise SystemExit("Không biết tên tài khoản Kaggle: dùng --username, biến KAGGLE_USERNAME hoặc ~/.kaggle/kaggle.json")
    return u


def build_kernel_dir(args) -> Path:
    if not SLUG_RE.match(args.slug):
        raise SystemExit("--slug chỉ gồm chữ thường, số, dấu gạch ngang (3-50 ký tự), ví dụ: pefr-vietnamese-nlp")
    user = kaggle_username(args.username)
    d = Path(args.build_dir or REPO / ".kaggle_build") / args.slug
    d.mkdir(parents=True, exist_ok=True)
    (d / "kaggle_entry.py").write_text(
        build_entry(Path(args.task), args.topic, 2 if args.quick else args.seeds, args.quick,
                    args.pip.split() if args.pip else None, args.time_budget, args.resume_from),
        encoding="utf-8")
    meta = {
        "id": f"{user}/{args.slug}", "title": args.slug.replace("-", " ").title(),
        "code_file": "kaggle_entry.py", "language": "python", "kernel_type": "script",
        "is_private": "true", "enable_gpu": "false" if args.no_gpu else "true", "enable_internet": "true",
        "dataset_sources": [], "competition_sources": [],
        "kernel_sources": [f"{user}/{args.resume_from}"] if args.resume_from else [],
    }
    (d / "kernel-metadata.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return d


def need_cli() -> str:
    exe = shutil.which("kaggle")
    if not exe:
        raise SystemExit("Chưa cài công cụ Kaggle: chạy `pip install kaggle`, rồi đặt token vào ~/.kaggle/kaggle.json "
                         "(Kaggle -> Settings -> API -> Create New Token).")
    return exe


def cmd_push(args) -> int:
    d = build_kernel_dir(args)
    print(f"Đã tạo thư mục kernel: {d}")
    if args.dry_run:
        print("--dry-run: chưa gửi lên Kaggle.")
        return 0
    r = subprocess.run([need_cli(), "kernels", "push", "-p", str(d)])
    if r.returncode == 0:
        user = kaggle_username(args.username)
        print(f"\nĐã gửi và xếp hàng chạy. Theo dõi: python experiments/run_on_kaggle.py status --slug {args.slug}\n"
              f"Xong thì tải về: python experiments/run_on_kaggle.py output --slug {args.slug} --dest <thư mục đề tài> "
              f"--topic \"{args.topic}\"\nHoặc xem trên web: https://www.kaggle.com/code/{user}/{args.slug}")
    return r.returncode


def cmd_status(args) -> int:
    return subprocess.run([need_cli(), "kernels", "status", f"{kaggle_username(args.username)}/{args.slug}"]).returncode


def cmd_output(args) -> int:
    dest = Path(args.dest)
    dest.mkdir(parents=True, exist_ok=True)
    rc = subprocess.run([need_cli(), "kernels", "output", f"{kaggle_username(args.username)}/{args.slug}",
                         "-p", str(dest)]).returncode
    if rc != 0:
        return rc
    sys.path.insert(0, str(REPO))
    from src.tools.experiments import ResultsError, load_results

    res_path = dest / "results.json"
    partial = dest / "results.partial.json"
    if partial.exists() and not res_path.exists():
        miss = json.loads(partial.read_text(encoding="utf-8")).get("missing", [])
        print(f"CHƯA ĐỦ: còn {len(miss)} lần chạy. Chạy lại (thêm --resume-from {args.slug}) để tiếp tục. Ví dụ thiếu:")
        for m in miss[:10]:
            print("  -", m)
        return 2
    if not res_path.exists():
        print("Không thấy results.json trong Output — xem log trên Kaggle (có thể lần chạy chưa xong hoặc bị lỗi).")
        return 3
    try:
        res = load_results(res_path, args.topic)
    except ResultsError as e:
        print("results.json KHÔNG hợp lệ:", e)
        return 4
    print(f"OK: {res_path} — {len(res.datasets)} dataset, {len(res.methods)} phương pháp, seeds={res.seeds}.")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--username", help="tên tài khoản Kaggle (mặc định lấy từ kaggle.json)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("push", help="đóng gói + gửi lên Kaggle để chạy")
    p.add_argument("--task", required=True)
    p.add_argument("--topic", required=True, help="tên đề tài (ghi vào results.json)")
    p.add_argument("--slug", required=True)
    p.add_argument("--seeds", type=int, default=5)
    p.add_argument("--quick", action="store_true", help="thử nhanh (KHÔNG dùng cho bài báo)")
    p.add_argument("--no-gpu", action="store_true")
    p.add_argument("--pip", default="", help='thư viện cần cài thêm, ví dụ "transformers datasets"')
    p.add_argument("--time-budget", type=float, default=None, help="phút; hết giờ thì dừng và lưu phần đã xong")
    p.add_argument("--resume-from", default=None, help="slug của lần chạy trước để nối tiếp nhật ký")
    p.add_argument("--build-dir", default=None)
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(fn=cmd_push)
    s = sub.add_parser("status", help="xem trạng thái")
    s.add_argument("--slug", required=True)
    s.set_defaults(fn=cmd_status)
    o = sub.add_parser("output", help="tải kết quả về và kiểm tra")
    o.add_argument("--slug", required=True)
    o.add_argument("--dest", required=True)
    o.add_argument("--topic", default=None)
    o.set_defaults(fn=cmd_output)
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
