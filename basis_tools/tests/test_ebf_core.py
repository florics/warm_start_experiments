from __future__ import annotations

import gzip
from pathlib import Path
import tempfile
import unittest
import zipfile

from basis_tools.ebf import (
    BasisStatus,
    BoundStatus,
    ConstraintBasisEntry,
    EBFValidationError,
    VariableBasisEntry,
    basis_exchange_distance,
    compare_ebf_bases,
    read_constraint_basis_csv,
    read_variable_basis_csv,
    validate_simplex_basis,
    write_constraint_basis_csv,
    write_variable_basis_csv,
)


class EBFCoreTests(unittest.TestCase):
    def _entries(self):
        variables = [
            VariableBasisEntry("z", BasisStatus.NONBASIC, BoundStatus.LOWER, 0.0),
            VariableBasisEntry("a", BasisStatus.BASIC, BoundStatus.INTERIOR, 2.5),
        ]
        constraints = [
            ConstraintBasisEntry("r2", BasisStatus.NONBASIC, BoundStatus.UPPER, 4.0),
            ConstraintBasisEntry("r1", BasisStatus.BASIC, BoundStatus.FIXED, 3.0),
        ]
        return variables, constraints

    def test_roundtrip_plain_and_sorted(self):
        variables, constraints = self._entries()
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            vp = td / "vars.csv"
            cp = td / "constrs.csv"
            write_variable_basis_csv(vp, variables)
            write_constraint_basis_csv(cp, constraints)
            self.assertEqual([e.var_name for e in read_variable_basis_csv(vp)], ["a", "z"])
            self.assertEqual([e.constr_name for e in read_constraint_basis_csv(cp)], ["r1", "r2"])

    def test_roundtrip_gzip(self):
        variables, constraints = self._entries()
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            vp = td / "vars.csv.gz"
            cp = td / "constrs.csv.gz"
            write_variable_basis_csv(vp, variables)
            write_constraint_basis_csv(cp, constraints)
            self.assertEqual(len(read_variable_basis_csv(vp)), 2)
            self.assertEqual(len(read_constraint_basis_csv(cp)), 2)
            with gzip.open(vp, "rt", encoding="utf-8") as f:
                self.assertTrue(f.readline().startswith("var_name,"))

    def test_read_zip(self):
        variables, constraints = self._entries()
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            plain_v = td / "vars.csv"
            plain_c = td / "constrs.csv"
            write_variable_basis_csv(plain_v, variables)
            write_constraint_basis_csv(plain_c, constraints)
            zip_v = td / "vars.csv.zip"
            zip_c = td / "constrs.csv.zip"
            with zipfile.ZipFile(zip_v, "w") as zf:
                zf.write(plain_v, arcname="vars.csv")
            with zipfile.ZipFile(zip_c, "w") as zf:
                zf.write(plain_c, arcname="constrs.csv")
            self.assertEqual(len(read_variable_basis_csv(zip_v)), 2)
            self.assertEqual(len(read_constraint_basis_csv(zip_c)), 2)

    def test_simplex_validation_and_distance(self):
        variables, constraints = self._entries()
        validate_simplex_basis(variables, constraints, num_rows=2)
        self.assertEqual(basis_exchange_distance(variables, constraints, variables, constraints), 0)
        with self.assertRaises(EBFValidationError):
            validate_simplex_basis(variables, constraints, num_rows=3)

    def test_compare_compressed_and_plain(self):
        variables, constraints = self._entries()
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            va, ca = td / "a_vars.csv", td / "a_constrs.csv"
            vb, cb = td / "b_vars.csv.gz", td / "b_constrs.csv.gz"
            write_variable_basis_csv(va, variables)
            write_constraint_basis_csv(ca, constraints)
            write_variable_basis_csv(vb, variables)
            write_constraint_basis_csv(cb, constraints)
            result = compare_ebf_bases(va, ca, vb, cb, print_result=False)
            self.assertEqual(result.variables.basis_status_differences, 0)
            self.assertEqual(result.constraints.basis_status_differences, 0)
            self.assertEqual(result.variables.max_abs_numerical_difference, 0.0)
            self.assertEqual(result.constraints.max_abs_numerical_difference, 0.0)


if __name__ == "__main__":
    unittest.main()
