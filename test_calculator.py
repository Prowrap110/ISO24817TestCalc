"""Numerical and R4 qualification regression tests, independent of the UI."""
import importlib.util
import math
import unittest


MODULE_SPEC = importlib.util.find_spec("calculator")
if MODULE_SPEC is not None:
    import calculator


class CalculatorTests(unittest.TestCase):
    def setUp(self):
        if MODULE_SPEC is None and self._testMethodName != "test_00_module_available":
            self.skipTest("Calculator module has not been implemented yet")

    def inputs(self, **changes):
        values = dict(calculator.DEFAULT_INPUTS)
        values.update(changes)
        return values

    def check(self, name, **changes):
        checks = calculator.calculate(self.inputs(**changes))["checks"]
        matches = [c for c in checks if c["name"] == name]
        self.assertEqual(len(matches), 1, f"Expected one check named {name}")
        self.assertIn(matches[0]["status"], {"PASS", "FAIL", "REVIEW"})
        self.assertTrue(matches[0]["detail"])
        return matches[0]["status"]

    def test_00_module_available(self):
        self.assertIsNotNone(MODULE_SPEC, "Implement calculator.py with calculate and DEFAULT_INPUTS")

    def test_reference_calculation_and_layer_rounding(self):
        r = calculator.calculate(self.inputs())
        self.assertAlmostEqual(r["pressure_mpa"], 12.27933070866, delta=1e-6)
        self.assertAlmostEqual(r["thickness_mm"], 6.860866696, delta=1e-6)
        self.assertEqual(r["plies"], 9)
        self.assertAlmostEqual(r["effective_thickness_mm"], 7.47, delta=1e-6)
        self.assertGreaterEqual(r["effective_thickness_mm"], r["thickness_mm"])
        self.assertLess(r["effective_thickness_mm"] - .83, r["thickness_mm"])

    def test_reference_spool_and_row_geometry(self):
        r = calculator.calculate(self.inputs())
        self.assertAlmostEqual(r["spool_length_limit_mm"], 3598, delta=1e-6)
        self.assertEqual(r["num_rows"], 2)
        self.assertAlmostEqual(r["laid_length_mm"], 550, delta=1e-6)

    def test_extra_row_when_two_rows_no_longer_cover(self):
        r = calculator.calculate(self.inputs(repair_length=551))
        self.assertEqual(r["num_rows"], 3)
        self.assertAlmostEqual(r["laid_length_mm"], 800, delta=1e-6)

    def test_circumferential_seam_is_counted_for_every_ply_and_row(self):
        a = calculator.calculate(self.inputs(seam_overlap=0))
        b = calculator.calculate(self.inputs(seam_overlap=50))
        self.assertAlmostEqual(b["cloth_length_m"] - a["cloth_length_m"],
                               b["num_rows"] * b["plies"] * .05, delta=1e-6)
        self.assertAlmostEqual(b["area_m2"], b["cloth_length_m"] * .3, delta=1e-6)

    def test_nominal_od_quantity_and_separate_waste_allowance(self):
        r = calculator.calculate(self.inputs(waste_percent=10))
        expected = 2 * 9 * (math.pi * 508 + 50) / 1000
        self.assertAlmostEqual(r["cloth_length_m"], expected, delta=1e-6)
        self.assertAlmostEqual(r["procurement_length_m"], expected * 1.1, delta=1e-6)
        no_waste = calculator.calculate(self.inputs(waste_percent=0))
        self.assertAlmostEqual(no_waste["cloth_length_m"], r["cloth_length_m"], delta=1e-6)
        self.assertAlmostEqual(no_waste["area_m2"], r["area_m2"], delta=1e-6)

    def test_boundary_dimensions_require_review(self):
        self.assertEqual(self.check("Defect length", defect_length=254), "REVIEW")
        self.assertEqual(self.check("Defect width", defect_width=127), "REVIEW")

    def test_undersized_defect_fails(self):
        self.assertEqual(self.check("Defect length", defect_length=253), "FAIL")
        self.assertEqual(self.check("Defect width", defect_width=126), "FAIL")

    def test_larger_defect_passes(self):
        self.assertEqual(self.check("Defect length", defect_length=255), "PASS")
        self.assertEqual(self.check("Defect width", defect_width=128), "PASS")

    def test_diameter_limit_is_strict(self):
        self.assertEqual(self.check("Diameter", od=100), "FAIL")
        self.assertEqual(self.check("Diameter", od=101), "PASS")

    def test_defect_depth_must_be_eighty_percent(self):
        self.assertEqual(self.check("Defect depth", remaining=1.74), "PASS")
        self.assertEqual(self.check("Defect depth", remaining=2), "FAIL")

    def test_spool_length_limit_is_strict(self):
        self.assertEqual(self.check("Spool length", spool_length=3598), "FAIL")
        self.assertEqual(self.check("Spool length", spool_length=3597), "FAIL")
        self.assertEqual(self.check("Spool length", spool_length=3599), "PASS")

    def test_measured_yield_requires_evidence(self):
        self.assertEqual(self.check("Measured yield", measured_yield_confirmed=False), "REVIEW")
        self.assertEqual(self.check("Measured yield", measured_yield_confirmed=True,
                                    mechanical_report="Mechanical report 24-152"), "PASS")

    def test_repair_design_reference_required(self):
        self.assertEqual(self.check("Repair design", repair_design_ref=""), "REVIEW")
        self.assertEqual(self.check("Repair design", repair_design_ref="Approved design R4-01"), "PASS")

    def test_invalid_numbers_and_overlap_raise_value_error(self):
        invalid = [
            {"od": 0}, {"od": -1}, {"wall": 0}, {"wall": -1},
            {"remaining": 0}, {"remaining": -1}, {"remaining": 8.7},
            {"remaining": 9}, {"yield_strength": 0},
            {"cloth_width": 0}, {"row_overlap": -1},
            {"row_overlap": 300}, {"row_overlap": 301},
            {"seam_overlap": -1}, {"waste_percent": -1},
        ]
        for key in ("od", "wall", "remaining", "yield_strength", "defect_length",
                    "defect_width", "repair_length", "spool_length", "cloth_width",
                    "row_overlap", "seam_overlap", "waste_percent"):
            invalid.extend({key: v} for v in (math.nan, math.inf, -math.inf))
        for change in invalid:
            with self.subTest(change=change), self.assertRaises(ValueError):
                calculator.calculate(self.inputs(**change))


if __name__ == "__main__":
    unittest.main()
