"""Checks against the installed Rebirth client. Skipped when the client isn't on this machine."""
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import extract_refs  # noqa: E402
import geo  # noqa: E402
from texture import texture_to_image  # noqa: E402

HAVE_CLIENT = os.path.isdir(os.path.join(extract_refs.CLIENT, "piggs"))


@unittest.skipUnless(HAVE_CLIENT, "Rebirth client not installed")
class ClientAssetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        found = extract_refs.matches("geo", r"player_library/MALE_SHIRT\.geo$")
        blob = next(iter(found.values()))[1]
        with tempfile.NamedTemporaryFile(suffix=".geo", delete=False) as tmp:
            tmp.write(blob)
        try:
            cls.models = geo.read_geo(tmp.name)
        finally:
            os.unlink(tmp.name)

    def test_every_triangle_index_is_in_range(self):
        for m in self.models:
            flat = [i for t in m.tris for i in t]
            self.assertGreaterEqual(min(flat), 0, m.name)
            self.assertLess(max(flat), len(m.verts), m.name)

    def test_normals_are_unit_length_and_uvs_sane(self):
        for m in self.models[:20]:
            for n in m.norms:
                self.assertAlmostEqual(sum(c * c for c in n) ** 0.5, 1.0, delta=0.02)
            # UVs may tile past 0..1; a decode error shows up as huge or NaN values instead.
            for u, v in m.sts:
                self.assertTrue(-16 <= u <= 16 and -16 <= v <= 16, m.name)

    def test_names_follow_geo_convention(self):
        self.assertIn("GEO_Chest_Tight", [m.name for m in self.models])
        self.assertTrue(all(m.name.startswith("GEO_") for m in self.models))

    def test_shirt_is_left_right_symmetric(self):
        # Mis-decoded 4-byte deltas once folded one sleeve; a correct T-pose shirt mirrors in X.
        tight = next(m for m in self.models if m.name == "GEO_Chest_Tight")
        xs = [v[0] for v in tight.verts]
        self.assertAlmostEqual(min(xs), -max(xs), delta=0.01)

    def test_ghost_face_texture_converts(self):
        found = extract_refs.matches("textures", r"Croatoa/Ghosts/Face_Skin_Croatoa_Ghost_02")
        img = texture_to_image(next(iter(found.values()))[1])
        self.assertEqual(img.size, (256, 128))


if __name__ == "__main__":
    unittest.main()
