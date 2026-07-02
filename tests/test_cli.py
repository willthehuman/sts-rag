from pathlib import Path
import tempfile
import unittest

from sts_rag.cli import main
from sts_rag.extract import DEFAULT_JAR


JAR = Path(DEFAULT_JAR)


@unittest.skipUnless(JAR.is_file(), "desktop-1.0.jar is not available")
class CliTests(unittest.TestCase):
    def test_ingest_and_ask_smoke(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "sts.sqlite"
            self.assertEqual(main(["ingest", "--jar", str(JAR), "--db", str(db), "--rebuild"]), 0)
            self.assertEqual(main(["ask", "--db", str(db), "--backend", "none", "what is the highest cost card?"]), 0)

    def test_chat_startup_eof(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "sts.sqlite"
            self.assertEqual(main(["chat", "--db", str(db), "--backend", "none"]), 0)


if __name__ == "__main__":
    unittest.main()

