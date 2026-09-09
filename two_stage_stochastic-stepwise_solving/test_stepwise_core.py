import random
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from stepwise_core import Coupling, disagreement, rank_violations, violation_summary
from stepwise_two_stage import without_rows
from basis_tools.mps_bas import BASIC, LOWER, BasisVectors


class StepwiseCoreTests(unittest.TestCase):
    def setUp(self):
        self.first = Coupling("a", "a", "a_base", "a_high", 0, 1)
        self.second = Coupling("b", "b", "b_base", "b_high", 2, 3)

    def test_uses_absolute_tolerance_for_satisfaction(self):
        item = disagreement(self.first, [1.0, 1.0 + 5e-7], 1e-6)
        self.assertTrue(item["satisfied"])
        self.assertIsNone(item["relative"])

    def test_relative_ordering(self):
        low = disagreement(self.first, [10.0, 9.0, 0.0, 0.0], 1e-9)
        high = disagreement(self.second, [10.0, 9.0, 10.0, 5.0], 1e-9)
        self.assertIs(rank_violations([low, high], "relative_ascending", random.Random(1)), low)
        self.assertIs(rank_violations([low, high], "relative_descending", random.Random(1)), high)
        self.assertEqual(violation_summary([low, high])["count"], 2)

    def test_random_strategy_is_reproducible(self):
        items = [disagreement(self.first, [2.0, 1.0, 0.0, 0.0], 1e-9), disagreement(self.second, [2.0, 1.0, 4.0, 1.0], 1e-9)]
        self.assertEqual(rank_violations(items, "random", random.Random(7))["coupling"], rank_violations(items, "random", random.Random(7))["coupling"])

    def test_removes_only_requested_basis_rows(self):
        basis = BasisVectors(["x"], ["r1", "r2"], [BASIC], [LOWER, BASIC])
        filtered = without_rows(basis, {"r2"})
        self.assertEqual(filtered.col_names, ["x"])
        self.assertEqual(filtered.row_names, ["r1"])
        self.assertEqual(filtered.col_status, [BASIC])
        self.assertEqual(filtered.row_status, [LOWER])


if __name__ == "__main__":
    unittest.main()
