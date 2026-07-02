from pathlib import Path
import tempfile
import unittest

from sts_rag.answer import answer_question
from sts_rag.db import connect, ingest_catalog, reset
from sts_rag.extract import DEFAULT_JAR, extract_catalog
from sts_rag.game_tools import build_game_tool_context
from sts_rag.retrieval import highest_cost_card, retrieve, strategy_context


JAR = Path(DEFAULT_JAR)


@unittest.skipUnless(JAR.is_file(), "desktop-1.0.jar is not available")
class QueryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.db_path = Path(cls.tmp.name) / "sts.sqlite"
        cls.conn = connect(cls.db_path)
        reset(cls.conn)
        ingest_catalog(cls.conn, extract_catalog(JAR))

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()
        cls.tmp.cleanup()

    def test_highest_cost_card(self):
        answer = highest_cost_card(self.conn)
        self.assertIn("Meteor Strike", answer["answer"])
        self.assertIn("5", answer["answer"])

    def test_starting_deck_exact_answer(self):
        answer = answer_question(
            self.conn,
            "what are the starting deck cards for ironclad",
            backend="ollama",
            model="unused-because-exact",
        )
        self.assertIn("5x Strike", answer)
        self.assertIn("4x Defend", answer)
        self.assertIn("1x Bash", answer)
        self.assertIn("character:ironclad", answer)

    def test_highest_cost_common_cards_exact_answer(self):
        answer = answer_question(
            self.conn,
            "what are the highest cost common cards",
            backend="ollama",
            model="unused-because-exact",
        )
        self.assertIn("among common cards is 2", answer)
        self.assertIn("Clothesline", answer)
        self.assertIn("Streamline", answer)
        self.assertNotIn("Meteor Strike", answer)

    def test_monsters_with_artifact_exact_answer(self):
        answer = answer_question(self.conn, "what monsters have artifacts?", backend="ollama")
        self.assertIn("Bronze Automaton", answer)
        self.assertIn("Sentry", answer)
        self.assertIn("monster:Sentry", answer)

    def test_shiv_matchup_answers(self):
        counters = answer_question(self.conn, "what monsters counter shiv decks?", backend="ollama")
        self.assertIn("Time Eater", counters)
        self.assertIn("Spiker", counters)
        self.assertIn("power:Time Warp", counters)
        weak = answer_question(self.conn, "what monsters are weak against a shiv deck?", backend="ollama")
        self.assertIn("Byrds", weak)
        self.assertIn("monster:Byrd", weak)
        self.assertIn("card:Blade Dance", weak)

    def test_minimalist_achievement_answer(self):
        answer = answer_question(
            self.conn,
            "can you help me with the achievement to win with a deck of 5 or less cards?",
            backend="ollama",
        )
        self.assertIn("Minimalist", answer)
        self.assertIn("5-card deck", answer)
        self.assertIn("achievement:minimalist", answer)

    def test_watcher_infinite_answer(self):
        answer = answer_question(
            self.conn,
            "what are ways to have an infinite deck with the watcher?",
            backend="none",
        )
        self.assertIn("Tool-guided answer", answer)
        self.assertIn("Rushdown", answer)
        self.assertIn("Violet Lotus", answer)
        self.assertIn("card:Adaptation", answer)

    def test_poison_relic_answer(self):
        answer = answer_question(
            self.conn,
            "what relics should i look for for a poison deck?",
            backend="none",
        )
        self.assertIn("Snecko Skull", answer)
        self.assertIn("Twisted Funnel", answer)
        self.assertIn("The Specimen", answer)
        self.assertIn("card:Catalyst", answer)

    def test_orb_limit_answer(self):
        answer = answer_question(
            self.conn,
            "what is the theorical limit of orbs",
            backend="none",
        )
        self.assertIn("No fixed numeric hard cap", answer)
        self.assertIn("Inserter", answer)
        self.assertIn("Capacitor", answer)

    def test_cross_character_mix_answer(self):
        answer = answer_question(
            self.conn,
            "what possible mix of two characters cards can be broken using cards events or relics that allows adding cards from other characters",
            backend="none",
        )
        self.assertIn("Prismatic Shard", answer)
        self.assertIn("Corruption", answer)
        self.assertIn("relic:PrismaticShard", answer)

    def test_game_tool_context_broadens_strategy_queries(self):
        context = build_game_tool_context(
            self.conn,
            "what are ways to have an infinite deck with the watcher?",
            limit=12,
        )
        names = {item.name for section in context["sections"] for item in section["items"]}
        self.assertIn("Rushdown", names)
        self.assertIn("Violet Lotus", names)
        self.assertIn("Sundial", names)

    def test_highest_cost_colorless_excludes_temp_cards(self):
        answer = answer_question(self.conn, "what are the highest cost colorless cards?", backend="ollama")
        self.assertIn("Apotheosis", answer)
        self.assertIn("The Bomb", answer)
        self.assertNotIn("Omega", answer)

    def test_block_strategy_fallback(self):
        answer = answer_question(
            self.conn,
            "which ironclad card has the most value considering i want to make a block deck",
            backend="none",
        )
        self.assertIn("Strategy", answer)
        self.assertIn("card:", answer)

    def test_infinite_ironclad_strategy_context(self):
        rows = strategy_context(self.conn, "come up with an infinite deck with ironclad", limit=8)
        citations = {row["citation"] for row in rows}
        self.assertIn("card:Dropkick", citations)
        self.assertIn("card:Offering", citations)
        self.assertNotIn("card:Infinite Blades", citations)

    def test_best_card_avoids_random_fts_hits(self):
        answer = answer_question(self.conn, "what is the best card", backend="none")
        self.assertIn("no objective", answer.lower())
        self.assertIn("card:", answer)
        self.assertNotIn("relic:Turnip", answer)

    def test_relic_lookup(self):
        rows = retrieve(self.conn, "Burning Blood relic", limit=5)
        self.assertTrue(any(row["entity_kind"] == "relic" and row["entity_id"] == "Burning Blood" for row in rows))

    def test_monster_move_lookup(self):
        rows = retrieve(self.conn, "Cultist Incantation", limit=5)
        self.assertTrue(any(row["entity_kind"] == "monster" and row["entity_id"] == "Cultist" for row in rows))


if __name__ == "__main__":
    unittest.main()
