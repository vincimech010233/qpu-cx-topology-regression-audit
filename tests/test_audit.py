from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from qpu_cx_audit.core import InputError, analyze, analyze_files, parse_snapshot, parse_workloads
from qpu_cx_audit.cli import main


BEFORE = {"name": "before", "num_qubits": 3, "native_cx": [[0, 1], [1, 0], [1, 2]]}
AFTER = {"name": "after", "num_qubits": 3, "native_cx": [[0, 1], [1, 0], [2, 1]]}


class AuditTests(unittest.TestCase):
    def test_added_removed_and_directed_edges(self):
        report = analyze(BEFORE, AFTER, [])
        self.assertEqual(report["native_cx_changes"], {"added": [[2, 1]], "removed": [[1, 2]]})

    def test_reversed_connection_is_distinct(self):
        report = analyze(
            {"name": "a", "num_qubits": 2, "native_cx": [[0, 1]]},
            {"name": "b", "num_qubits": 2, "native_cx": [[1, 0]]},
            [{"id": "w", "operations": [[0, 1], [1, 0]]}],
        )
        self.assertEqual(report["native_cx_changes"]["added"], [[1, 0]])
        self.assertEqual(report["native_cx_changes"]["removed"], [[0, 1]])
        self.assertEqual(report["workloads"][0]["unavailable_operation_occurrences_before"], 1)
        self.assertEqual(report["workloads"][0]["unavailable_operation_occurrences_after"], 1)
        self.assertEqual(report["workloads"][0]["classification"], "REGRESSION")
        self.assertEqual(report["workloads"][0]["became_unavailable_after"], [[0, 1]])
        self.assertEqual(report["workloads"][0]["became_available_after"], [[1, 0]])

    def test_regression_improvement_and_no_workload_impact(self):
        regression = analyze(BEFORE, AFTER, [{"id": "r", "operations": [[1, 2]]}])
        self.assertEqual(regression["workload_summary"]["classification"], "REGRESSION")
        improvement = analyze(AFTER, BEFORE, [{"id": "i", "operations": [[1, 2]]}])
        self.assertEqual(improvement["workload_summary"]["classification"], "IMPROVEMENT")
        irrelevant = analyze(BEFORE, AFTER, [{"id": "u", "operations": [[0, 1]]}])
        self.assertEqual(irrelevant["workload_summary"]["classification"], "NO_WORKLOAD_IMPACT")

    def test_overall_regression_is_not_hidden_by_an_improvement_elsewhere(self):
        report = analyze(BEFORE, AFTER, [
            {"id": "regressed", "operations": [[1, 2]]},
            {"id": "improved", "operations": [[2, 1]]},
        ])
        self.assertEqual(report["workload_summary"]["unavailable_operation_occurrences_before"], 1)
        self.assertEqual(report["workload_summary"]["unavailable_operation_occurrences_after"], 1)
        self.assertEqual(report["workload_summary"]["classification"], "REGRESSION")

    def test_unchanged_configuration_and_empty_workloads(self):
        report = analyze(BEFORE, BEFORE, [])
        self.assertEqual(report["workload_summary"], {
            "classification": "UNCHANGED", "workload_count": 0,
            "unavailable_operation_occurrences_before": 0,
            "unavailable_operation_occurrences_after": 0,
        })
        self.assertEqual(report["native_cx_changes"], {"added": [], "removed": []})

    def test_empty_operation_workload_is_unchanged(self):
        report = analyze(BEFORE, AFTER, [{"id": "empty", "operations": []}])
        self.assertEqual(report["workloads"][0]["classification"], "UNCHANGED")
        self.assertEqual(report["workload_summary"]["classification"], "NO_WORKLOAD_IMPACT")

    def test_occurrences_are_counted_but_missing_edges_are_unique(self):
        report = analyze(BEFORE, AFTER, [{"id": "repeat", "operations": [[1, 2], [1, 2]]}])
        workload = report["workloads"][0]
        self.assertEqual(workload["unavailable_operation_occurrences_after"], 2)
        self.assertEqual(workload["missing_native_cx_after"], [[1, 2]])

    def test_workloads_sorted_for_deterministic_report(self):
        report = analyze(BEFORE, BEFORE, [
            {"id": "z", "operations": []}, {"id": "a", "operations": []}
        ])
        self.assertEqual([w["id"] for w in report["workloads"]], ["a", "z"])

    def test_snapshot_rejects_wrong_shape_extra_missing_types_and_duplicate_edges(self):
        bad = [
            [], {"name": "x", "num_qubits": 1},
            {"name": "x", "num_qubits": True, "native_cx": []},
            {"name": "x", "num_qubits": 0, "native_cx": []},
            {"name": "x", "num_qubits": 2, "native_cx": [[0, 1], [0, 1]]},
            {"name": "x", "num_qubits": 2, "native_cx": [[1, 1]]},
            {"name": "x", "num_qubits": 2, "native_cx": [[0, 2]]},
            {"name": "x", "num_qubits": 2, "native_cx": [[0, "1"]]},
            {"name": "x", "num_qubits": 2, "native_cx": [], "extra": 1},
            {"name": " ", "num_qubits": 2, "native_cx": []},
        ]
        for value in bad:
            with self.subTest(value=value), self.assertRaises(InputError):
                parse_snapshot(value)

    def test_rejects_qubit_count_mismatch_and_bad_workloads(self):
        changed = {"name": "after", "num_qubits": 2, "native_cx": []}
        with self.assertRaises(InputError):
            analyze(BEFORE, changed, [])
        for workloads in (None, {}, [{"id": "x", "operations": [[3, 1]]}],
                          [{"id": "x", "operations": "bad"}],
                          [{"id": "", "operations": []}],
                          [{"id": "x", "operations": []}, {"id": "x", "operations": []}],
                          [{"id": "x", "operations": [], "extra": True}]):
            with self.subTest(workloads=workloads), self.assertRaises(InputError):
                parse_workloads(workloads, 3)

    def test_json_reader_rejects_malformed_duplicate_keys_and_nonstandard_constant(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "input.json"
            for content in ('{', '{"name":"a","name":"b"}', '{"x": NaN}'):
                path.write_text(content, encoding="utf-8")
                with self.subTest(content=content), self.assertRaises(InputError):
                    analyze_files(path, path, path)

    def test_rejects_unpaired_surrogates(self):
        invalid = {"name": "\ud800", "num_qubits": 1, "native_cx": []}
        with self.assertRaisesRegex(InputError, "surrogates"):
            analyze(invalid, invalid, [])

    def test_missing_file_and_non_utf8(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "missing.json"
            with self.assertRaisesRegex(InputError, "not found"):
                analyze_files(missing, missing, missing)
            bad = Path(tmp) / "bad.json"
            bad.write_bytes(b"\xff")
            with self.assertRaisesRegex(InputError, "cannot read"):
                analyze_files(bad, bad, bad)

    def test_cli_writes_consistent_json_and_markdown(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            inputs = []
            for name, value in (("before.json", BEFORE), ("after.json", AFTER), ("workloads.json", [])):
                path = tmp_path / name
                path.write_text(json.dumps(value), encoding="utf-8")
                inputs.append(path)
            output = tmp_path / "out"
            output.mkdir()
            self.assertEqual(main([*(str(path) for path in inputs), "--output-dir", str(output)]), 0)
            report = json.loads((output / "report.json").read_text(encoding="utf-8"))
            markdown = (output / "report.md").read_text(encoding="utf-8")
            self.assertIn("NO_WORKLOAD_IMPACT", report["workload_summary"]["classification"])
            self.assertIn("Removed native directed CX", markdown)
            self.assertEqual(main([*(str(path) for path in inputs), "--output-dir", str(output)]), 0)
            self.assertEqual((output / "report.json").read_text(encoding="utf-8"),
                             json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n")

    def test_markdown_escapes_untrusted_workload_ids_and_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            values = (("b.json", {**BEFORE, "name": "before|\n**FAKE**"}),
                      ("a.json", AFTER),
                      ("w.json", [{"id": "safe|id`\n| EVIL | REGRESSION |", "operations": []}]))
            inputs = []
            for name, value in values:
                path = base / name
                path.write_text(json.dumps(value), encoding="utf-8")
                inputs.append(path)
            output = base / "out"
            output.mkdir()
            self.assertEqual(main([*(str(path) for path in inputs), "--output-dir", str(output)]), 0)
            markdown = (output / "report.md").read_text(encoding="utf-8")
            self.assertNotIn("\n**FAKE**", markdown)
            self.assertNotIn("\n| EVIL |", markdown)
            self.assertIn("safe\\|id\\`", markdown)

    def test_cli_input_error_and_output_error_exit_codes(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            self.assertEqual(main([str(base / "missing"), str(base / "missing"), str(base / "missing")]), 2)
            paths = []
            for name, value in (("b", BEFORE), ("a", AFTER), ("w", [])):
                path = base / name
                path.write_text(json.dumps(value), encoding="utf-8")
                paths.append(str(path))
            self.assertEqual(main([*paths, "--output-dir", str(base / "absent")]), 3)

    def test_cli_refuses_to_overwrite_input_or_follow_symlink_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            paths = []
            for name, value in (("report.json", BEFORE), ("a.json", AFTER), ("w.json", [])):
                path = base / name
                path.write_text(json.dumps(value), encoding="utf-8")
                paths.append(path)
            self.assertEqual(main([*(str(p) for p in paths), "--output-dir", str(base)]), 3)
            subdir = base / "out"
            subdir.mkdir()
            (subdir / "report.json").symlink_to(paths[0])
            self.assertEqual(main([*(str(p) for p in paths), "--output-dir", str(subdir)]), 3)
            self.assertTrue(paths[0].read_text(encoding="utf-8").startswith("{"))

    def test_module_cli_executes_offline(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            b, a, w = base / "b.json", base / "a.json", base / "w.json"
            for path, value in ((b, BEFORE), (a, AFTER), (w, [])):
                path.write_text(json.dumps(value), encoding="utf-8")
            output = base / "out"
            output.mkdir()
            env = dict(os.environ)
            env["PYTHONPATH"] = str(ROOT / "src")
            completed = subprocess.run(
                [sys.executable, "-m", "qpu_cx_audit", str(b), str(a), str(w), "--output-dir", str(output)],
                cwd=base, env=env, text=True, capture_output=True, check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertTrue((output / "report.json").exists())


if __name__ == "__main__":
    unittest.main()
