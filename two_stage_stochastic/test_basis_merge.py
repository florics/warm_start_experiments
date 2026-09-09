from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from basis_tools.mps_bas import BASIC, LOWER, UPPER, reorder_basis_vectors, write_mps_bas
from two_stage_stochastic.basis_merge import build_combined_basis
from two_stage_stochastic.construct_two_stage_basis import initial_dual_feasibility_from_log


class TwoStageBasisMergeTest(unittest.TestCase):
    def test_extracts_initial_dual_feasibility_evidence(self) -> None:
        samples = {
            "gurobi": "        0    1.0e+09   1.0e+03   0.000000e+00      0s\n",
            "copt": "Dual             0    1.0e+09           14           0       0.00s\n",
            "xpress": "     0       1.0e+09      D     14     0        .000000     0\n",
            "highs": "Solving LP with useful basis so presolve not used\n",
        }
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            for solver, text in samples.items():
                log = directory / f"{solver}.log"
                log.write_text(text, encoding="utf-8")
                result = initial_dual_feasibility_from_log(solver, log)
                self.assertNotEqual(result["status"], "NOT_REPORTED")
                if solver != "highs":
                    self.assertTrue(result["dual_feasible"])

    def test_combines_bases_and_keeps_coupling_rows_basic(self) -> None:
        columns = ["InvestmentFlowBlock_capacity(asset_0)", "flow(asset_0_0)"]
        rows = ["c_e_balance(asset_0)_", "c_u_emission_limit_"]
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            first_bas = directory / "first.bas"
            second_bas = directory / "second.bas"
            write_mps_bas(first_bas, columns, rows, [BASIC, LOWER], [LOWER, BASIC])
            write_mps_bas(second_bas, columns, rows, [UPPER, BASIC], [BASIC, UPPER])

            combined = build_combined_basis(
                first_bas,
                second_bas,
                columns,
                rows,
                columns,
                rows,
                ["InvestmentFlowBlock_capacity(asset_0)"],
                "base",
                "demand_up",
            )

        self.assertEqual(
            combined.col_names,
            [
                "InvestmentFlowBlock_capacity(asset_0_base)",
                "flow(asset_0_0_base)",
                "InvestmentFlowBlock_capacity(asset_0_demand_up)",
                "flow(asset_0_0_demand_up)",
            ],
        )
        self.assertEqual(
            combined.row_names,
            [
                "c_e_balance(asset_0_base)_",
                "c_u_emission_limit_base_",
                "c_e_balance(asset_0_demand_up)_",
                "c_u_emission_limit_demand_up_",
                "c_e_nonanticipativity_(InvestmentFlowBlock_capacity(asset_0)_base_demand_up)_",
            ],
        )
        self.assertEqual(combined.col_status, [BASIC, LOWER, UPPER, BASIC])
        self.assertEqual(combined.row_status, [LOWER, BASIC, BASIC, UPPER, BASIC])
        self.assertEqual(sum(status == BASIC for status in combined.col_status + combined.row_status), len(combined.row_names))

        reordered = reorder_basis_vectors(
            combined,
            [combined.col_names[1], combined.col_names[0], *combined.col_names[2:]],
            [combined.row_names[1], combined.row_names[0], *combined.row_names[2:]],
        )
        self.assertEqual(reordered.col_status[:2], [LOWER, BASIC])
        self.assertEqual(reordered.row_status[:2], [BASIC, LOWER])


if __name__ == "__main__":
    unittest.main()
