"""Run: python -m unittest discover -s tests

The fixture under tests/fixture/data is SYNTHETIC: it mimics the Cryptic text format with the
real Necromancy identifiers, but the field layout is a stand-in for the maintainers' real files.
"""
import copy
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import cryptic_text as ct  # noqa: E402
from generate import Gen  # noqa: E402

DATA = os.path.join(ROOT, "tests", "fixture", "data")
with open(os.path.join(ROOT, "spec", "spirit_binding.json"), encoding="utf-8") as f:
    SPEC = json.load(f)


def run(spec=SPEC):
    return Gen(copy.deepcopy(spec), DATA).run()


class TokenTests(unittest.TestCase):
    def test_dotted_names_do_not_match_inside_longer_names(self):
        text = "Mastermind_Pets.Zombie Mastermind_Pets.Zombie_2.Enchant Mastermind_Pets.Zombie.Resistance"
        out, n = ct.replace_tokens(text, {"Mastermind_Pets.Zombie": "X"})
        self.assertEqual(out, "X Mastermind_Pets.Zombie_2.Enchant Mastermind_Pets.Zombie.Resistance")
        self.assertEqual(n, 1)

    def test_braces_inside_strings_and_comments_are_ignored(self):
        text = 'A\n{\n\tName "x { y"\n\t// }\n}\nB\n{\n}\n'
        self.assertEqual([b.keyword for b in ct.parse(text)], ["A", "B"])


class GenerateTests(unittest.TestCase):
    def setUp(self):
        self.g = run()
        self.assertEqual(self.g.errors, [])

    def out(self, rel):
        return self.g.outputs[rel]

    def test_summon_creates_new_pets(self):
        txt = self.out("defs/powers/Mastermind_Summon_Spirit_Binding.powers")
        self.assertEqual(txt.count("EntityDef MastermindPets_Restless_Spirit"), 3)
        self.assertNotIn("MastermindPets_Zombie", txt)

    def test_upgrade_targets_new_pets_and_kits(self):
        txt = self.out("defs/powers/Mastermind_Summon_Spirit_Binding.powers")
        self.assertIn("target.VillainName MastermindPets_Wailing_Shade eq", txt)
        self.assertIn("Reward Mastermind_Pets.Wailing_Shade_2.Hack", txt)

    def test_kit_override_takes_body_from_ghost_power(self):
        txt = self.out("defs/powers/Mastermind_Pets_Restless_Spirit.powers")
        self.assertIn("FullName Mastermind_Pets.Restless_Spirit.Ghastly_Blast", txt)
        self.assertNotIn("Zombie_Brawl", txt)

    def test_villain_uses_new_kit_and_costumes(self):
        txt = self.g.new_text["Defs/Villains/MastermindPets.villain"]
        self.assertIn("PowerSet Restless_Spirit", txt)
        self.assertIn("Costume Spirit_Restless_03", txt)
        self.assertNotIn("Necromancy_", txt)

    def test_template_files_keep_original_content(self):
        with open(os.path.join(DATA, "Defs", "Villains", "MastermindPets.villain"), encoding="latin-1", newline="") as f:
            original = f.read()
        self.assertTrue(self.out("Defs/Villains/MastermindPets.villain").startswith(original.rstrip()))

    def test_category_lists_new_set_after_template(self):
        lines = self.out("defs/powers/Player_Mastermind_Summon.categories").replace("\r", "").split("\n")
        i = lines.index("\tPowerSets Mastermind_Summon.Necromancy")
        self.assertEqual(lines[i + 1], "\tPowerSets Mastermind_Summon.Spirit_Binding")

    def test_tint_and_scale(self):
        txt = self.out("Defs/V_Mastermind_Pets/V_Mastermind_Spirit_Binding.nd")
        lord = txt[txt.index("Name Spirit_Lord_01"):]
        self.assertIn("Scale 15", lord.split("CostumePart")[0])
        self.assertIn("Color1  216, 255, 242", lord)


class CountTests(unittest.TestCase):
    def count_for(self, n):
        spec = copy.deepcopy(SPEC)
        spec["pets"][0]["count"] = n
        g = run(spec)
        return g.outputs["defs/powers/Mastermind_Summon_Spirit_Binding.powers"].count(
            "EntityDef MastermindPets_Restless_Spirit")

    def test_more_pets(self):
        self.assertEqual(self.count_for(5), 5)

    def test_fewer_pets(self):
        self.assertEqual(self.count_for(1), 1)


class LintTests(unittest.TestCase):
    def test_missing_template_power_is_an_error(self):
        spec = copy.deepcopy(SPEC)
        spec["powers"][0]["template"] = "Not_A_Power"
        g = run(spec)
        self.assertTrue(any("Not_A_Power" in e for e in g.errors))


if __name__ == "__main__":
    unittest.main()
