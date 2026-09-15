import csv
from pathlib import Path
import tempfile
import unittest

from two_stage_stochastic.input_csv import INPUT_COLUMNS, MULTI_INPUT_COLUMNS, read_input_csv, read_multi_input_csv


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

    def test_reads_multi_scenario_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.csv"
            with path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=MULTI_INPUT_COLUMNS); writer.writeheader()
                for name in ("base", "low", "high"):
                    writer.writerow({"integrated_lp": "models/integrated.lp.gz", "lp": f"models/{name}.lp", "bas": f"bases/{name}.bas.gz", "scenarioname": name})
            integrated, scenarios = read_multi_input_csv(path)
            self.assertEqual(integrated, path.parent / "models/integrated.lp.gz")
            self.assertEqual([name for name, _lp, _bas in scenarios], ["base", "low", "high"])


if __name__ == "__main__": unittest.main()
