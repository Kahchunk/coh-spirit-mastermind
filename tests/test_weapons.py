"""Custom weapon generation over the SYNTHETIC fixture (stand-in for the maintainers' files)."""
import copy
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
from generate import Gen  # noqa: E402

DATA = os.path.join(ROOT, "tests", "fixture", "data")
with open(os.path.join(ROOT, "spec", "heavy_ordnance_weapons.json"), encoding="utf-8") as f:
    SPEC = json.load(f)


def run(spec=SPEC):
    return Gen(copy.deepcopy(spec), DATA).run()


class WeaponTests(unittest.TestCase):
    def setUp(self):
        self.g = run()
        self.assertEqual(self.g.errors, [])

    def test_entity_points_at_new_geometry(self):
        txt = self.g.outputs["ent_types/CustomWeapon_HeavyOrdnance_RocketLauncher01.txt"]
        self.assertIn("player_library/G_WepR_HeavyOrdnance_RocketLauncher01.geo", txt)
        self.assertNotIn("Council01", txt)

    def test_fx_for_every_body_type(self):
        for prefix in ("Male", "Fem", "Huge"):
            txt = self.g.outputs[f"fx/WEAPONS/Custom_HeavyOrdnance/{prefix}_HeavyOrdnance_GrenadeLauncher01.fx"]
            self.assertIn("EntityType CustomWeapon_HeavyOrdnance_GrenadeLauncher01", txt)

    def test_layered_texture_uses_new_base_and_mask(self):
        added = self.g.new_text["tricks/WEAPONS/CustomWeapons.txt"]
        self.assertIn("Texture X_CustomWeapon_HeavyOrdnance_RocketLauncher01", added)
        self.assertIn("Mask WepR_HeavyOrdnance_RocketLauncher01_Mask", added)
        self.assertIn("Base WepR_HeavyOrdnance_RocketLauncher01", added)

    def test_menu_entries_in_spec_order_without_template_key(self):
        menu = self.g.outputs["menu/costume/localized/male/all/weapons/inc_weapons_assaultrifles.ctm"]
        order = [menu.index(f'"{w["label"]}"') for w in SPEC["custom_weapons"]["weapons"] if w["template"] == "Council01"]
        self.assertEqual(order, sorted(order))
        added = self.g.new_text["menu/costume/localized/male/all/weapons/inc_weapons_assaultrifles.ctm"]
        self.assertNotIn("CustomWeapon_Council_01", added)
        self.assertIn("Key CustomWeapon_Council_01", menu)  # original entry untouched

    def test_unlock_key_can_be_set(self):
        spec = copy.deepcopy(SPEC)
        spec["custom_weapons"]["weapons"][0]["unlock_key"] = "CustomWeapon_HeavyOrdnance_01"
        added = run(spec).new_text["menu/costume/localized/huge/all/weapons/inc_weapons_assaultrifles.ctm"]
        self.assertIn("Key CustomWeapon_HeavyOrdnance_01", added)

    def test_missing_trick_template_is_an_error(self):
        spec = copy.deepcopy(SPEC)
        spec["custom_weapons"]["weapons"][0]["trick_template"] = "X_Nope"
        self.assertTrue(any("X_Nope" in e for e in run(spec).errors))


if __name__ == "__main__":
    unittest.main()
