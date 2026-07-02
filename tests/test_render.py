import io
import os
import unittest
from unittest import mock

from rich.console import Console

from sts_rag import render


def _rendered(text, *, no_color=False):
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=True, no_color=no_color, width=120)
    render.render_answer(console, text)
    return buf.getvalue()


ESC = "\x1b"


class RenderTests(unittest.TestCase):
    def test_colored_output_has_ansi_and_renders_markdown(self):
        out = _rendered("Poison payoffs:\n- Catalyst: doubles Poison [card:Catalyst]\n(model: x/y)")
        self.assertIn(ESC, out)
        # markdown rendering produces ANSI codes
        self.assertIn("Catalyst", out)
        self.assertIn("[card:Catalyst]", out)

    def test_no_color_strips_color_but_keeps_text(self):
        out = _rendered("Poison payoffs:\n- Catalyst: doubles Poison [card:Catalyst]", no_color=True)
        self.assertNotIn("36m", out)  # no cyan color code
        self.assertIn("Catalyst", out)
        self.assertIn("[card:Catalyst]", out)

    @mock.patch.dict(os.environ, {"NO_COLOR": "1"}, clear=False)
    def test_no_color_env_disables_color(self):
        buf = io.StringIO()
        console = render.build_console()
        console.file = buf
        console._force_terminal = True
        render.render_answer(console, "Header:\n- Bash: hit [card:Bash]")
        out = buf.getvalue()
        self.assertNotIn("36m", out)
        self.assertIn("Bash", out)


if __name__ == "__main__":
    unittest.main()
