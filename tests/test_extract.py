from pathlib import Path
import unittest

from sts_rag.extract import DEFAULT_JAR, extract_catalog


JAR = Path(DEFAULT_JAR)


@unittest.skipUnless(JAR.is_file(), "desktop-1.0.jar is not available")
class ExtractJarTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = extract_catalog(JAR)
        cls.by_kind_id = {(e.kind, e.entity_id): e for e in cls.catalog.entities}
        cls.by_kind_name = {(e.kind, e.name): e for e in cls.catalog.entities}

    def test_known_entities(self):
        self.assertIn(("card", "Bash"), self.by_kind_id)
        self.assertIn(("card", "Meteor Strike"), self.by_kind_id)
        self.assertIn(("relic", "Burning Blood"), self.by_kind_id)
        self.assertIn(("monster", "Cultist"), self.by_kind_id)
        self.assertIn(("character", "ironclad"), self.by_kind_id)
        self.assertIn(("achievement", "minimalist"), self.by_kind_id)

    def test_counts_are_in_expected_range(self):
        stats = self.catalog.stats
        self.assertGreaterEqual(stats.get("card", 0), 430)
        self.assertLessEqual(stats.get("card", 0), 445)
        self.assertGreaterEqual(stats.get("relic", 0), 180)
        self.assertLessEqual(stats.get("relic", 0), 205)
        self.assertGreaterEqual(stats.get("monster", 0), 70)
        self.assertLessEqual(stats.get("monster", 0), 75)

    def test_card_facts(self):
        bash = self.by_kind_id[("card", "Bash")]
        self.assertEqual(bash.facts.get("cost"), 2)
        self.assertEqual(bash.facts.get("damage"), 8)
        self.assertEqual(bash.facts.get("magic_number"), 2)
        self.assertIn("Deal 8 damage", bash.data.get("rendered_description", ""))
        meteor = self.by_kind_id[("card", "Meteor Strike")]
        self.assertEqual(meteor.facts.get("cost"), 5)

    def test_character_starting_deck(self):
        ironclad = self.by_kind_id[("character", "ironclad")]
        self.assertEqual(
            ironclad.data.get("starting_deck"),
            ["Strike_R", "Strike_R", "Strike_R", "Strike_R", "Strike_R",
             "Defend_R", "Defend_R", "Defend_R", "Defend_R", "Bash"],
        )

    def test_monster_power_refs(self):
        sentry = self.by_kind_id[("monster", "Sentry")]
        self.assertIn("ArtifactPower", sentry.facts.get("referenced_powers", []))
        spiker = self.by_kind_id[("monster", "Spiker")]
        self.assertIn("ThornsPower", spiker.facts.get("referenced_powers", []))


if __name__ == "__main__":
    unittest.main()
