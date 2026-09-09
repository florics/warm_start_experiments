import csv
from pathlib import Path
import tempfile
import unittest

from two_stage_stochastic.input_csv import INPUT_COLUMNS, read_input_csv


class InputCsvTests(unittest.TestCase):
    def test_relative_paths_resolve_from_csv_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.csv"
            with path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=INPUT_COLUMNS); writer.writeheader()
                writer.writerow({"integrated_lp": "models/integrated.lp.gz", "first_lp": "models/first.lp", "first_bas": "bases/first.bas.gz", "first_scenarioname": "base", "second_lp": "models/second.lp", "second_bas": "bases/second.bas.gz", "second_scenarioname": "high"})
            row = read_input_csv(path)
            self.assertEqual(row["integrated_lp"], path.parent / "models/integrated.lp.gz")
            self.assertEqual(row["first_scenarioname"], "base")

    def test_requires_exactly_one_row(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.csv"; path.write_text(",".join(INPUT_COLUMNS) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "exactly one"):
                read_input_csv(path)


if __name__ == "__main__": unittest.main()
