"""Rich rendering for the interactive chat UI.

`answer_question` returns a plain string using stable conventions (headers ending with ':',
'- ' bullets, `[kind:id]` citations, a trailing '(model: ...)' line). This module styles those
conventions with `rich` for the `chat` command only; the `ask` command still prints the raw
string so it stays scriptable/pipeable. Rich handles Windows VT, `NO_COLOR`, and tty detection.
"""

from __future__ import annotations

import re

from rich.console import Console
from rich.panel import Panel
from rich.text import Text


CITATION_RE = re.compile(r"\[[a-z_]+:[^\]]+\]")
MODEL_RE = re.compile(r"^\(model: .+\)$")
BULLET_RE = re.compile(r"^(\s*)-\s+(.*)$")
STEP_RE = re.compile(r"^\s*\d+[.)]\s+")
NOTE_PREFIXES = ("Note:", "Strategy/speculation", "Speculation:", "Model note:", "Web note:")

CITATION_STYLE = "dim italic"
HEADER_STYLE = "bold cyan"
NOTE_STYLE = "yellow italic"
BULLET_GLYPH = "•"
SUBBULLET_GLYPH = "◦"


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
    ascii_only = not _supports_unicode(console)
    for raw in text.split("\n"):
        console.print(_render_line(raw, ascii_only=ascii_only))


def _supports_unicode(console: Console) -> bool:
    encoding = console.encoding or "utf-8"
    try:
        (BULLET_GLYPH + SUBBULLET_GLYPH + "›").encode(encoding)
        return True
    except (UnicodeEncodeError, LookupError):
        return False


def _render_line(raw: str, *, ascii_only: bool = False) -> Text:
    stripped = raw.strip()
    if not stripped:
        return Text("")

    if MODEL_RE.match(stripped):
        return _with_citations(raw, "dim")

    if any(stripped.startswith(prefix) for prefix in NOTE_PREFIXES):
        return _with_citations(raw, NOTE_STYLE)

    bullet = BULLET_RE.match(raw)
    if bullet:
        indent, body = bullet.group(1), bullet.group(2)
        if ascii_only:
            glyph = "-" if len(indent) < 2 else "*"
        else:
            glyph = SUBBULLET_GLYPH if len(indent) >= 2 else BULLET_GLYPH
        text = Text(indent)
        text.append(f"{glyph} ", style="cyan")
        name, sep, rest = _split_name(body)
        text.append_text(_with_citations(name, "bold"))
        if sep:
            text.append(sep)
            text.append_text(_with_citations(rest, ""))
        return text

    if STEP_RE.match(raw):
        return _with_citations(raw, "green")

    if stripped.endswith(":") and len(stripped) <= 60 and not CITATION_RE.search(stripped):
        return Text(raw, style=HEADER_STYLE)

    return _with_citations(raw, "")


def _split_name(body: str) -> tuple[str, str, str]:
    """Split a bullet body into (entity-name, separator, remainder) at the first ' - ' or ': '."""
    candidates = [body.find(" - "), body.find(": ")]
    positions = [pos for pos in candidates if pos != -1]
    if not positions:
        return body, "", ""
    cut = min(positions)
    sep_len = 3 if body[cut:cut + 3] == " - " else 2
    return body[:cut], body[cut:cut + sep_len], body[cut + sep_len:]


def _with_citations(text: str, base_style: str) -> Text:
    result = Text()
    pos = 0
    for match in CITATION_RE.finditer(text):
        if match.start() > pos:
            result.append(text[pos:match.start()], style=base_style or None)
        result.append(match.group(0), style=CITATION_STYLE)
        pos = match.end()
    if pos < len(text):
        result.append(text[pos:], style=base_style or None)
    return result
