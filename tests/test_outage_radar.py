# Copyright (C) 2026 Jean-François Brisson / Spark AI NLP. SPDX-License-Identifier: AGPL-3.0-only
import ast
import contextlib
import copy
import hashlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import outage_radar  # noqa: E402

SAMPLE_OUTPUT_SHA256 = "77e3bf4bfb67db478950a27a78383ce1d05014f47dfda31c5d84997a70fb60ff"


class OutageRadarTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with (ROOT / "examples" / "sample_input.json").open(encoding="utf-8") as handle:
            cls.sample = json.load(handle)

    def signal(self, result, service):
        return next(item for item in result["signals"] if item["service"] == service)

    def test_example_demonstrates_requested_classifications(self):
        result = outage_radar.analyze(self.sample)
        expected = {
            "catalog": "site-local/connectivity-path",
            "frontend": "no observed failure",
            "inventory": "insufficient evidence/unknown",
            "invoicing": "dependency-wide",
            "payments": "dependency-wide",
            "search": "likely service-wide",
        }
        actual = {item["service"]: item["classification"] for item in result["signals"]}
        self.assertEqual(actual, expected)
        self.assertEqual(set(expected.values()), outage_radar.CLASSIFICATIONS)

    def test_missing_and_unknown_probes_do_not_count_toward_quorum(self):
        signal = self.signal(outage_radar.analyze(self.sample), "inventory")
        evidence = signal["evidence"]
        self.assertEqual(signal["classification"], "insufficient evidence/unknown")
        self.assertEqual(evidence["usable_sites_count"], 1)
        self.assertFalse(evidence["quorum_met"])
        self.assertEqual(evidence["failed_sites"], ["north"])
        self.assertEqual(evidence["unknown_sites"], ["south"])
        self.assertEqual(evidence["missing_sites"], ["east", "west"])

    def test_dependency_wide_requires_service_and_dependency_failures_to_overlap(self):
        document = copy.deepcopy(self.sample)
        for check in document["dependency_checks"]:
            if check["site"] == "west":
                check["status"] = "ok"
        invoicing = self.signal(outage_radar.analyze(document), "invoicing")
        self.assertEqual(invoicing["classification"], "likely service-wide")
        ledger = invoicing["evidence"]["dependencies"][0]
        self.assertEqual(ledger["co_failing_service_sites"], ["east", "north"])

    def test_subquorum_multisite_failure_is_unknown_not_service_wide(self):
        document = {
            "schema_version": 1,
            "observed_at": "2026-09-30T09:15:00Z",
            "sites": ["a", "b", "c"],
            "minimum_quorum_sites": 3,
            "services": [{"id": "api", "dependencies": []}],
            "service_checks": [
                {"site": "a", "service": "api", "status": "fail"},
                {"site": "b", "service": "api", "status": "fail"},
                {"site": "c", "service": "api", "status": "ok"},
            ],
            "dependency_checks": [],
        }
        signal = outage_radar.analyze(document)["signals"][0]
        self.assertEqual(signal["classification"], "insufficient evidence/unknown")
        self.assertTrue(signal["evidence"]["quorum_met"])

    def test_dependency_wide_requires_a_declared_dependency(self):
        # 'search' fails at every site that 'ledger-db' fails at, but does not declare it.
        signal = self.signal(outage_radar.analyze(self.sample), "search")
        self.assertEqual(signal["classification"], "likely service-wide")
        self.assertEqual(signal["evidence"]["dependencies"], [])

        document = copy.deepcopy(self.sample)
        for service in document["services"]:
            if service["id"] == "search":
                service["dependencies"] = ["ledger-db"]
        signal = self.signal(outage_radar.analyze(document), "search")
        self.assertEqual(signal["classification"], "dependency-wide")
        self.assertEqual(signal["evidence"]["dependencies"][0]["co_failing_service_sites"], ["east", "north", "west"])

    def test_dependency_overlap_below_quorum_falls_back_to_service_wide(self):
        document = copy.deepcopy(self.sample)
        for check in document["dependency_checks"]:
            if check["site"] in {"north", "west"}:
                check["status"] = "unknown"
        signal = self.signal(outage_radar.analyze(document), "payments")
        self.assertEqual(signal["classification"], "likely service-wide")
        self.assertEqual(signal["evidence"]["dependencies"][0]["unknown_sites"], ["north", "west"])

    def test_single_failure_below_quorum_is_not_site_local(self):
        document = {
            "schema_version": 1,
            "observed_at": "2026-09-30T09:15:00+02:00",
            "sites": ["a", "b", "c"],
            "minimum_quorum_sites": 3,
            "services": [{"id": "api", "dependencies": []}],
            "service_checks": [
                {"site": "a", "service": "api", "status": "fail"},
                {"site": "b", "service": "api", "status": "ok"},
                {"site": "c", "service": "api", "status": "unknown"},
            ],
            "dependency_checks": [],
        }
        signal = outage_radar.analyze(document)["signals"][0]
        self.assertEqual(signal["classification"], "insufficient evidence/unknown")
        self.assertFalse(signal["evidence"]["quorum_met"])
        document["service_checks"][2]["status"] = "ok"
        signal = outage_radar.analyze(document)["signals"][0]
        self.assertEqual(signal["classification"], "site-local/connectivity-path")

    def test_healthy_snapshot_below_quorum_is_not_reported_as_healthy(self):
        document = {
            "schema_version": 1,
            "observed_at": "2026-09-30T09:15:00Z",
            "sites": ["a", "b", "c"],
            "minimum_quorum_sites": 3,
            "services": [{"id": "api", "dependencies": []}],
            "service_checks": [
                {"site": "a", "service": "api", "status": "ok"},
                {"site": "b", "service": "api", "status": "ok"},
            ],
            "dependency_checks": [],
        }
        signal = outage_radar.analyze(document)["signals"][0]
        self.assertEqual(signal["classification"], "insufficient evidence/unknown")
        self.assertEqual(signal["evidence"]["missing_sites"], ["c"])

    def test_json_rendering_is_deterministic_and_independent_of_input_order(self):
        document = copy.deepcopy(self.sample)
        expected = outage_radar._render_json(outage_radar.analyze(document))
        self.assertEqual(expected, outage_radar._render_json(outage_radar.analyze(document)))
        document["sites"].reverse()
        document["services"].reverse()
        document["service_checks"].reverse()
        document["dependency_checks"].reverse()
        self.assertEqual(expected, outage_radar._render_json(outage_radar.analyze(document)))

    def test_schema_rejects_malformed_documents(self):
        malformed_documents = []

        missing_key = copy.deepcopy(self.sample)
        del missing_key["dependency_checks"]
        malformed_documents.append(missing_key)

        unknown_site = copy.deepcopy(self.sample)
        unknown_site["service_checks"][0]["site"] = "not-configured"
        malformed_documents.append(unknown_site)

        duplicate_probe = copy.deepcopy(self.sample)
        duplicate_probe["service_checks"].append(copy.deepcopy(duplicate_probe["service_checks"][0]))
        malformed_documents.append(duplicate_probe)

        invalid_status = copy.deepcopy(self.sample)
        invalid_status["service_checks"][0]["status"] = {"status": "ok"}
        malformed_documents.append(invalid_status)

        invalid_timestamp = copy.deepcopy(self.sample)
        invalid_timestamp["observed_at"] = "yesterday"
        malformed_documents.append(invalid_timestamp)

        invalid_quorum = copy.deepcopy(self.sample)
        invalid_quorum["minimum_quorum_sites"] = True
        malformed_documents.append(invalid_quorum)

        naive_timestamp = copy.deepcopy(self.sample)
        naive_timestamp["observed_at"] = "2026-09-30T09:15:00"
        malformed_documents.append(naive_timestamp)

        quorum_too_large = copy.deepcopy(self.sample)
        quorum_too_large["minimum_quorum_sites"] = 5
        malformed_documents.append(quorum_too_large)

        quorum_too_small = copy.deepcopy(self.sample)
        quorum_too_small["minimum_quorum_sites"] = 1
        malformed_documents.append(quorum_too_small)

        wrong_version = copy.deepcopy(self.sample)
        wrong_version["schema_version"] = 2
        malformed_documents.append(wrong_version)

        extra_key = copy.deepcopy(self.sample)
        extra_key["notes"] = "x"
        malformed_documents.append(extra_key)

        undeclared_dependency = copy.deepcopy(self.sample)
        undeclared_dependency["dependency_checks"][0]["dependency"] = "cache"
        malformed_documents.append(undeclared_dependency)

        undeclared_service = copy.deepcopy(self.sample)
        undeclared_service["service_checks"][0]["service"] = "billing"
        malformed_documents.append(undeclared_service)

        duplicate_service = copy.deepcopy(self.sample)
        duplicate_service["services"].append({"id": "catalog", "dependencies": []})
        malformed_documents.append(duplicate_service)

        padded_site = copy.deepcopy(self.sample)
        padded_site["sites"][0] = " east"
        malformed_documents.append(padded_site)

        for document in malformed_documents:
            with self.subTest(document=document):
                with self.assertRaises(outage_radar.InputError):
                    outage_radar.analyze(document)

    def test_duplicate_json_keys_are_rejected(self):
        with self.assertRaisesRegex(outage_radar.InputError, "duplicate JSON object key"):
            json.loads('{"schema_version":1,"schema_version":1}', object_pairs_hook=outage_radar._unique_object)

    def test_cli_rejects_malformed_json_without_writing_output(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "bad.json"
            source.write_text('{"schema_version":', encoding="utf-8")
            stdout = io.StringIO()
            stderr = io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                status = outage_radar.main(["--input", str(source)])
        self.assertEqual(status, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("invalid JSON", stderr.getvalue())

    def run_cli(self, *args):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            status = outage_radar.main(list(args))
        return status, stdout.getvalue(), stderr.getvalue()

    def test_cli_rejects_duplicate_keys_nan_and_non_utf8_input(self):
        cases = {
            "dup.json": ('{"schema_version":1,"schema_version":1}'.encode(), "duplicate JSON object key"),
            "nan.json": (b'{"schema_version": NaN}', "invalid JSON numeric constant"),
            "latin1.json": ('{"sites": ["caf\u00e9"]}'.encode("latin-1"), "not valid UTF-8"),
        }
        with tempfile.TemporaryDirectory() as directory:
            for name, (payload, message) in cases.items():
                with self.subTest(name=name):
                    source = Path(directory) / name
                    source.write_bytes(payload)
                    target = Path(directory) / (name + ".out")
                    status, stdout, stderr = self.run_cli("--input", str(source), "--output", str(target))
                    self.assertEqual(status, 2)
                    self.assertEqual(stdout, "")
                    self.assertIn(message, stderr)
                    self.assertFalse(target.exists())

    def test_cli_reports_missing_input_file(self):
        status, stdout, stderr = self.run_cli("--input", str(ROOT / "examples" / "does-not-exist.json"))
        self.assertEqual(status, 2)
        self.assertEqual(stdout, "")
        self.assertIn("error:", stderr)

    def test_cli_reproduces_committed_sample_output(self):
        committed = (ROOT / "examples" / "sample_output.json").read_bytes()
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "out.json"
            status, stdout, stderr = self.run_cli(
                "--input", str(ROOT / "examples" / "sample_input.json"), "--output", str(target)
            )
            self.assertEqual((status, stdout, stderr), (0, "", ""))
            self.assertEqual(target.read_bytes(), committed)
        status, stdout, _ = self.run_cli("--input", str(ROOT / "examples" / "sample_input.json"))
        self.assertEqual(status, 0)
        self.assertEqual(stdout.encode("utf-8"), committed)

    def test_sample_output_hash_is_pinned(self):
        # Update deliberately (and bump schema_version if the format changes) when output changes.
        rendered = outage_radar._render_json(outage_radar.analyze(self.sample)).encode("utf-8")
        self.assertEqual(hashlib.sha256(rendered).hexdigest(), SAMPLE_OUTPUT_SHA256)

    def test_module_imports_only_offline_standard_library_modules(self):
        tree = ast.parse((ROOT / "outage_radar.py").read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add((node.module or "").split(".")[0])
        allowed = {"__future__", "argparse", "datetime", "json", "pathlib", "sys", "typing"}
        self.assertLessEqual(imported, allowed)


if __name__ == "__main__":
    unittest.main()
