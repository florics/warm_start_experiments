from __future__ import annotations

import gzip
from pathlib import Path
import tempfile
import unittest
import zipfile

from basis_tools.io_utils import (
    CompressionIOError,
    logical_suffix,
    materialize_input,
    materialize_output,
    open_text_read,
    validate_input_suffix,
)


class CompressedIOTests(unittest.TestCase):
    def test_logical_suffix(self):
        self.assertEqual(logical_suffix("x.lp"), ".lp")
        self.assertEqual(logical_suffix("x.lp.gz"), ".lp")
        self.assertEqual(logical_suffix("x.lp.zip"), ".lp")

    def test_materialize_gzip_input(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            source = td / "model.lp.gz"
            with gzip.open(source, "wt", encoding="utf-8") as f:
                f.write("Minimize\n obj: x\nEnd\n")
            with materialize_input(source, expected_suffix=".lp") as local:
                self.assertEqual(local.suffix, ".lp")
                self.assertIn("Minimize", local.read_text())

    def test_materialize_zip_input(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            archive = td / "basis.zip"
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("basis.bas", "NAME B\nENDATA\n")
            with materialize_input(archive, expected_suffix=".bas") as local:
                self.assertEqual(local.suffix, ".bas")
                self.assertTrue(local.read_text().startswith("NAME"))

    def test_zip_must_have_one_member(self):
        with tempfile.TemporaryDirectory() as td:
            archive = Path(td) / "model.lp.zip"
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("a.lp", "a")
                zf.writestr("b.lp", "b")
            with self.assertRaises(CompressionIOError):
                with open_text_read(archive):
                    pass

    def test_materialize_gzip_output(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "basis.bas.gz"
            with materialize_output(target, expected_suffix=".bas") as local:
                self.assertEqual(local.suffix, ".bas")
                local.write_text("NAME B\nENDATA\n")
            with gzip.open(target, "rt", encoding="utf-8") as f:
                self.assertTrue(f.read().startswith("NAME"))

    def test_suffix_validation(self):
        
        with tempfile.TemporaryDirectory() as td:
            archive = Path(td) / "x.zip"
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("x.bas", "NAME B\nENDATA\n")
            validate_input_suffix(archive, ".bas")
        with self.assertRaises(ValueError):
            validate_input_suffix("x.lp.gz", ".bas")


if __name__ == "__main__":
    unittest.main()
