import asyncio

import typer
from rich.console import Console

from src.config import load_config
from src.orchestrator import Orchestrator

app = typer.Typer(help="AI Scientist - automated research & paper writing")
console = Console()


@app.command()
def run(config: str = "config.yaml"):
    """Chạy full pipeline: khảo sát tài liệu -> giả thuyết -> viết bài -> hình/bảng -> PDF -> tự bình duyệt."""
    cfg = load_config(config)
    asyncio.run(Orchestrator(cfg).run())


@app.command()
def topic(text: str, config: str = "config.yaml"):
    """Ghi đè topic rồi chạy full pipeline."""
    cfg = load_config(config)
    cfg.research.topic = text
    asyncio.run(Orchestrator(cfg).run())


@app.command()
def doctor():
    """Kiểm tra môi trường: API key, trình biên dịch LaTeX có sẵn không."""
    from src.tools.pdf_compiler import detect_engine

    try:
        cfg = load_config("config.yaml")
        console.print(f"[green]✓[/green] Config OK — model='{cfg.llm.model}' base_url='{cfg.base_url}'")
    except Exception as e:  # noqa: BLE001
        console.print(f"[red]✗ Config lỗi:[/red] {e}")

    try:
        import reportlab
        console.print(f"[green]✓[/green] ReportLab {reportlab.Version} — xuất PDF chính (paper.pdf) luôn khả dụng, không cần LaTeX")
    except ImportError:
        console.print("[red]✗ Thiếu reportlab[/red] — chạy: pip install -r requirements.txt")

    engine = detect_engine()
    if engine:
        console.print(f"[green]✓[/green] (Tuỳ chọn) Có LaTeX: {engine} — sẽ tạo thêm paper_latex.pdf")
    else:
        console.print("[dim]ℹ (Tuỳ chọn) Chưa cài LaTeX — không sao, paper.pdf vẫn được tạo đầy đủ bằng ReportLab.[/dim]")


if __name__ == "__main__":
    app()
