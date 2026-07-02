import tempfile
import unittest
from pathlib import Path

from sts_rag import creative
from sts_rag.db import connect, insert_entity, reset
from sts_rag.extract import ExtractedEntity
from sts_rag.retrieval import entity_detail_answer, exact_answer, find_entity_by_name


def _card(entity_id, name, description, facts):
    return ExtractedEntity(
        kind="card",
        entity_id=entity_id,
        name=name,
        source_path=f"com/megacrit/cardcrawl/cards/{entity_id}.class",
        data={"description": description, "rendered_description": description},
        facts=facts,
    )


def _relic(entity_id, name, description, facts):
    return ExtractedEntity(
        kind="relic",
        entity_id=entity_id,
        name=name,
        source_path=f"com/megacrit/cardcrawl/relics/{entity_id}.class",
        data={"description": description},
        facts=facts,
    )


def _seed_db(conn):
    entities = [
        _card("Catalyst", "Catalyst", "Double your Poison.", {"color": "GREEN", "character": "Silent", "type": "SKILL", "rarity": "RARE", "cost": 1}),
        _card("NoxiousFumes", "Noxious Fumes", "At the start of each turn, apply Poison.", {"color": "GREEN", "character": "Silent", "type": "POWER", "rarity": "UNCOMMON", "cost": 1}),
        _card("Bash", "Bash", "Deal 8 damage. Apply 2 Vulnerable.", {"color": "RED", "character": "Ironclad", "type": "ATTACK", "rarity": "BASIC", "cost": 2}),
        _relic("SneckoSkull", "Snecko Skull", "Whenever you apply Poison, apply 1 additional Poison.", {"tier": "COMMON"}),
        _relic("VioletLotus", "Violet Lotus", "Whenever you exit Calm, gain an additional Energy.", {"tier": "BOSS"}),
    ]
    for entity in entities:
        insert_entity(conn, entity)
    conn.commit()


class CreativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.conn = connect(Path(cls.tmp.name) / "sts.sqlite")
        reset(cls.conn)
        _seed_db(cls.conn)

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()
        cls.tmp.cleanup()

    def test_archetype_selected_by_color_and_mechanic(self):
        tool_context = {"plan": {"color": "Silent", "mechanics": ["poison"], "intent": "strategy"}}
        ideas = creative.build_creative_ideas(self.conn, "poison deck ideas", tool_context)
        names = [idea.name for idea in ideas]
        self.assertIn("Catalyst poison stack", names)

    def test_unknown_seeds_are_dropped(self):
        tool_context = {"plan": {"color": "Silent", "mechanics": ["poison"], "intent": "strategy"}}
        ideas = creative.build_creative_ideas(self.conn, "poison deck ideas", tool_context)
        poison = next(idea for idea in ideas if idea.name == "Catalyst poison stack")
        piece_names = {piece.name for piece in poison.pieces}
        # present in the fabricated DB
        self.assertIn("Catalyst", piece_names)
        self.assertIn("Noxious Fumes", piece_names)
        self.assertIn("Snecko Skull", piece_names)
        # absent seeds must not appear as citable pieces
        self.assertNotIn("Corpse Explosion", piece_names)
        for piece in poison.pieces:
            self.assertTrue(piece.citation.startswith(("card:", "relic:", "power:")))

    def test_no_ideas_without_matching_color(self):
        tool_context = {"plan": {"color": "Defect", "mechanics": ["orb"], "intent": "strategy"}}
        ideas = creative.build_creative_ideas(self.conn, "orb deck", tool_context)
        # Defect archetype seeds are not in the tiny DB, so nothing validates.
        self.assertEqual(ideas, [])

    def test_find_entity_by_name_normalizes(self):
        ent = find_entity_by_name(self.conn, "violet lotus")
        self.assertIsNotNone(ent)
        self.assertEqual(ent["name"], "Violet Lotus")
        self.assertEqual(ent["kind"], "relic")

    def test_entity_detail_answer(self):
        answer = entity_detail_answer(self.conn, "violet lotus")
        self.assertIsNotNone(answer)
        self.assertIn("Violet Lotus (relic)", answer["answer"])
        self.assertIn("Facts: Boss relic", answer["answer"])
        self.assertIn("exit Calm", answer["answer"])
        self.assertTrue(answer["citations"])

    def test_lookup_intent_dispatches_to_detail(self):
        answer = exact_answer(self.conn, "can you give details on violet lotus")
        self.assertIsNotNone(answer)
        self.assertIn("Violet Lotus (relic)", answer["answer"])

    def test_synergy_for_entity_matches_mechanic(self):
        ent = find_entity_by_name(self.conn, "noxious fumes")
        partners = creative.synergy_for_entity(
            self.conn, color=ent["facts"].get("color"), text=ent["text"], kind=ent["kind"], limit=5
        )
        names = {p.name for p in partners}
        # Poison text should surface other poison payoffs (e.g. Catalyst / Snecko Skull).
        self.assertTrue({"Catalyst", "Snecko Skull"} & names)


if __name__ == "__main__":
    unittest.main()
