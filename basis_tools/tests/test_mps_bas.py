from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
import zipfile

from basis_tools.mps_bas import BASIC, LOWER, UPPER, parse_mps_bas, write_mps_bas


class MpsBasTests(unittest.TestCase):
    def setUp(self):
        self.cols = ["x", "y"]
        self.rows = ["r1", "r2"]
        self.col_status = [BASIC, LOWER]
        self.row_status = [UPPER, BASIC]

    def _assert_basis(self, basis):
        self.assertEqual(basis.col_names, self.cols)
        self.assertEqual(basis.row_names, self.rows)
        self.assertEqual(basis.col_status, self.col_status)
        self.assertEqual(basis.row_status, self.row_status)

    def test_plain_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "basis.bas"
            write_mps_bas(path, self.cols, self.rows, self.col_status, self.row_status)
            self._assert_basis(parse_mps_bas(path, self.cols, self.rows))

    def test_gzip_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "basis.bas.gz"
            write_mps_bas(path, self.cols, self.rows, self.col_status, self.row_status)
            self._assert_basis(parse_mps_bas(path, self.cols, self.rows))

    def test_zip_read(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            plain = td / "basis.bas"
            archive = td / "basis.bas.zip"
            write_mps_bas(plain, self.cols, self.rows, self.col_status, self.row_status)
            with zipfile.ZipFile(archive, "w") as zf:
                zf.write(plain, arcname="basis.bas")
            self._assert_basis(parse_mps_bas(archive, self.cols, self.rows))


if __name__ == "__main__":
    unittest.main()
