"""Biên dịch LaTeX -> PDF.

Thứ tự ưu tiên công cụ: tectonic (khuyên dùng, 1 file, tự tải package) > latexmk > pdflatex+bibtex.
Chạy subprocess trong thread (asyncio.to_thread) để chạy được trên mọi hệ điều hành
(kể cả Windows + uvicorn --reload, nơi asyncio subprocess không khả dụng).
"""
from __future__ import annotations

import asyncio
import io
import re
import shutil
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

INSTALL_HINT = (
    "Chưa tìm thấy trình biên dịch LaTeX. Cài 1 trong các lựa chọn: "
    "tectonic (https://tectonic-typesetting.github.io — nhẹ nhất), "
    "TeX Live (Linux/macOS) hoặc MiKTeX (Windows). "
    "Hoặc tải paper_bundle.zip và upload lên https://www.overleaf.com để biên dịch."
)


@dataclass
class CompileResult:
    ok: bool
    pdf: bytes | None = None
    engine: str | None = None
    log: str = ""
    errors: list[str] = field(default_factory=list)


def detect_engine() -> str | None:
    for name in ("tectonic", "latexmk", "pdflatex"):
        if shutil.which(name):
            return name
    return None


def _run(cmd: list[str], cwd: Path, timeout: int) -> tuple[int, str]:
    try:
        p = subprocess.run(
            cmd, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, timeout=timeout, text=True, errors="replace",
        )
        return p.returncode, p.stdout
    except subprocess.TimeoutExpired as e:
        out = e.stdout.decode("utf-8", "replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
        return 124, out + f"\n[timeout sau {timeout}s]"
    except FileNotFoundError as e:
        return 127, str(e)


def _extract_errors(log: str) -> list[str]:
    errs = []
    for m in re.finditer(r"^(?:\./)?(?:[\w./-]+:\d+:)?\s*(!.*|.*error:.*)$", log, flags=re.M | re.I):
        line = m.group(1).strip()
        if line and line not in errs:
            errs.append(line[:200])
    return errs[:8]


def _compile_sync(tex: str, bib: str, assets: dict[str, bytes], timeout: int) -> CompileResult:
    engine = detect_engine()
    if engine is None:
        return CompileResult(False, engine=None, log=INSTALL_HINT, errors=[INSTALL_HINT])

    with tempfile.TemporaryDirectory(prefix="paper_") as tmp:
        d = Path(tmp)
        (d / "paper.tex").write_text(tex, encoding="utf-8")
        (d / "references.bib").write_text(bib or "", encoding="utf-8")
        for name, data in assets.items():
            (d / Path(name).name).write_bytes(data)

        logs: list[str] = []
        rc = 0
        if engine == "tectonic":
            rc, out = _run(["tectonic", "-X", "compile", "paper.tex"], d, timeout)
            if rc == 2 or "unrecognized" in out.lower():  # tectonic V1 CLI
                rc, out = _run(["tectonic", "paper.tex"], d, timeout)
            logs.append(out)
        elif engine == "latexmk":
            rc, out = _run(["latexmk", "-pdf", "-interaction=nonstopmode", "-file-line-error",
                            "paper.tex"], d, timeout)
            logs.append(out)
        else:  # pdflatex thủ công
            base = ["pdflatex", "-interaction=nonstopmode", "-file-line-error", "paper.tex"]
            rc, out = _run(base, d, timeout); logs.append(out)
            if shutil.which("bibtex") and bib.strip():
                _, out = _run(["bibtex", "paper"], d, timeout); logs.append(out)
                _, out = _run(base, d, timeout); logs.append(out)
            rc, out = _run(base, d, timeout); logs.append(out)

        log = "\n".join(logs)
        pdf_path = d / "paper.pdf"
        pdf = pdf_path.read_bytes() if pdf_path.exists() else None
        errors = _extract_errors(log)
        ok = pdf is not None and len(pdf) > 1000
        if ok and rc != 0:
            errors.insert(0, f"PDF đã tạo nhưng {engine} trả mã lỗi {rc} (có cảnh báo/lỗi nhẹ)")
        return CompileResult(ok, pdf if ok else None, engine, log[-8000:], errors)


async def compile_pdf(tex: str, bib: str, assets: dict[str, bytes], timeout: int = 240) -> CompileResult:
    return await asyncio.to_thread(_compile_sync, tex, bib, assets, timeout)


def build_bundle(tex: str, bib: str, assets: dict[str, bytes], pdf: bytes | None = None) -> bytes:
    """Gói zip (paper.tex + references.bib + hình [+ paper.pdf]) để upload lên Overleaf."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("paper.tex", tex)
        z.writestr("references.bib", bib or "")
        for name, data in assets.items():
            z.writestr(Path(name).name, data)
        if pdf:
            z.writestr("paper.pdf", pdf)
        z.writestr(
            "README.txt",
            "Biên dịch: pdflatex paper && bibtex paper && pdflatex paper && pdflatex paper\n"
            "Hoặc upload toàn bộ file zip này lên Overleaf (chọn compiler: pdfLaTeX).\n",
        )
    return buf.getvalue()
