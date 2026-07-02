"""Rich rendering for the interactive chat UI.

`answer_question` returns a plain string. This module renders it with `rich.markdown.Markdown`
for the `chat` command only; the `ask` command still prints the raw string so it stays
scriptable/pipeable. Rich handles Windows VT, `NO_COLOR`, and tty detection.
"""

from __future__ import annotations

import re

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text


MODEL_RE = re.compile(r"^\(model: .+\)$", re.MULTILINE)
CITATION_RE = re.compile(r"\[([a-z_]+:[^\]]+)\]")

BULLET_GLYPH = "•"


def build_console(*, no_color: bool = False) -> Console:
    """A console for chat output. `no_color` forces plain text; rich still honors NO_COLOR/tty."""
    return Console(no_color=no_color, highlight=False)


def render_banner(console: Console, *, backend: str, web: bool) -> None:
    body = Text()
    body.append("Ask about cards, relics, monsters, combos, or deck ideas.\n")
    body.append("Try: ", style="dim")
    body.append("\"give details on violet lotus\"", style="italic")
    body.append("  or  ", style="dim")
    body.append("\"infinite deck ideas for the watcher\"", style="italic")
    body.append("\nType ", style="dim")
    body.append("exit", style="bold")
    body.append(" or press Ctrl-Z/Ctrl-D to quit.", style="dim")
    subtitle = f"backend={backend}" + (" · web" if web else "")
    console.print(Panel(body, title="sts-rag chat", subtitle=subtitle, border_style="cyan", expand=False))


def render_prompt(console: Console) -> str:
    """Read a line with a styled prompt. Raises EOFError on Ctrl-Z/Ctrl-D like input()."""
    marker = "›" if _supports_unicode(console) else ">"
    return console.input(f"[bold cyan]{marker}[/] ").strip()


def render_answer(console: Console, text: str) -> None:
    model_match = MODEL_RE.search(text)
    model_line = model_match.group(0) if model_match else None
    body = MODEL_RE.sub("", text).rstrip() if model_match else text

    body = CITATION_RE.sub(r"\\[\1\\]", body)
    console.print(Markdown(body))

    if model_line:
        console.print(Text(model_line, style="dim"))


def _supports_unicode(console: Console) -> bool:
    encoding = console.encoding or "utf-8"
    try:
        (BULLET_GLYPH + "›").encode(encoding)
        return True
    except (UnicodeEncodeError, LookupError):
        return False
