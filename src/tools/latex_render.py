from pathlib import Path

from jinja2 import Environment, FileSystemLoader


def _make_env(template_path: str) -> tuple[Environment, str]:
    template_file = Path(template_path)
    env = Environment(
        loader=FileSystemLoader(str(template_file.parent)),
        block_start_string="<%",
        block_end_string="%>",
        variable_start_string="<<",
        variable_end_string=">>",
        comment_start_string="<#",
        comment_end_string="#>",
    )
    return env, template_file.name


def render_latex_to_string(template_path: str, context: dict) -> str:
    """Trả về nội dung LaTeX dạng string (để lưu DB)."""
    env, name = _make_env(template_path)
    return env.get_template(name).render(**context)


def render_latex(template_path: str, context: dict, output_path: str) -> None:
    """Render và ghi ra file (cho CLI)."""
    content = render_latex_to_string(template_path, context)
    Path(output_path).write_text(content, encoding="utf-8")