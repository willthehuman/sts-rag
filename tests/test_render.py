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
    def test_colored_output_has_ansi_and_styles_citation(self):
        out = _rendered("Poison payoffs:\n- Catalyst: doubles Poison [card:Catalyst]\n(model: x/y)")
        self.assertIn(ESC, out)
        # header is bold cyan (36), citation is dim (2)
        self.assertIn("36m", out)
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

    def test_ascii_fallback_glyph(self):
        line = render._render_line("- Catalyst: doubles Poison", ascii_only=True)
        self.assertTrue(line.plain.startswith("- "))
        sub = render._render_line("  - nested item", ascii_only=True)
        self.assertIn("* ", sub.plain)

    def test_unicode_glyph_when_supported(self):
        line = render._render_line("- Catalyst: doubles Poison", ascii_only=False)
        self.assertIn(render.BULLET_GLYPH, line.plain)

    def test_split_name(self):
        self.assertEqual(render._split_name("Catalyst: doubles Poison"), ("Catalyst", ": ", "doubles Poison"))
        self.assertEqual(render._split_name("Dropkick loop - draws a card"), ("Dropkick loop", " - ", "draws a card"))
        self.assertEqual(render._split_name("no separator here"), ("no separator here", "", ""))

    def test_citations_split_into_spans(self):
        text = render._with_citations("see [card:Bash] now", "bold")
        self.assertEqual(text.plain, "see [card:Bash] now")
        # the citation span carries the dim/italic style
        styles = [str(span_style) for _s, _e, span_style in text.spans]
        self.assertIn(render.CITATION_STYLE, styles)


if __name__ == "__main__":
    unittest.main()
