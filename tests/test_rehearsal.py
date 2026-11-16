import io
import shutil
import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path
from rehearsal.backend import ApiError, BotoBackend, FixtureBackend, validate_endpoint
from rehearsal.workflow import Fault, Gateway, Workflow
from rehearsal.runner import run_suite
from rehearsal.report import write_reports


@contextmanager
def temporary_output():
    # Python 3.14's mode-0700 temporary directories can be inaccessible to a
    # restricted Windows runner. Keep disposable test output in the workspace.
    root = (Path.cwd() / "reports" / "test-tmp").resolve()
    folder = root / uuid.uuid4().hex
    folder.mkdir(parents=True)
    try:
        yield folder
    finally:
        if not folder.resolve().is_relative_to(root):
            raise RuntimeError("Refusing cleanup outside the test output directory")
        shutil.rmtree(folder)


class RehearsalTests(unittest.TestCase):
    def setUp(self):
        self.backend = FixtureBackend()
        self.gateway = Gateway(self.backend)
        self.delays = []
        self.workflow = Workflow(self.gateway, sleep=self.delays.append)

    def seed(self, count=5):
        for name in ("test-source", "test-archive", "test-restore"):
            self.backend.call("create_bucket", Bucket=name)
        for i in range(count):
            self.backend.call("put_object", Bucket="test-source", Key=str(i), Body=f"object-{i}".encode())

    def test_six_scenarios_and_cleanup(self):
        report = run_suite(self.backend, backend_name="unit-test fixture")
        self.assertEqual(report["passed"], 6)
        self.assertEqual(self.backend.buckets, {})
        self.assertFalse(report["aws_parity_verified"])
        self.assertFalse(report["eon_integration"])

    def test_repeated_runs_are_semantically_repeatable(self):
        first = run_suite(self.backend, backend_name="unit-test fixture")
        second = run_suite(self.backend, backend_name="unit-test fixture")
        signature = lambda r: [(s["id"], s["passed"], s["retries"], s["checks"]) for s in r["scenarios"]]
        self.assertEqual(signature(first), signature(second))
        self.assertNotEqual(first["run_id"], second["run_id"])

    def test_refuses_remote_or_ambiguous_endpoints(self):
        for url in ("https://s3.amazonaws.com", "http://127.0.0.1:9297", "https://localhost:9297",
                    "https://127.0.0.1.evil.test:9297", "https://127.0.0.1:9297/path",
                    "https://user:secret@127.0.0.1:9297", "https://127.0.0.1:9297?x=y",
                    "https://127.0.0.1:9297#x", "https://127.0.0.1", "https://127.0.0.1:0"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                validate_endpoint(url)
        self.assertEqual(validate_endpoint("https://127.0.0.1:9297/"), "https://127.0.0.1:9297")

    def test_missing_emulator_files_never_fall_back_to_aws_credentials(self):
        with temporary_output() as folder, self.assertRaises(ValueError):
            BotoBackend("https://127.0.0.1:9297", Path(folder))

    def test_pagination_keeps_all_objects(self):
        self.seed(7)
        self.assertEqual(len(self.workflow.objects("test-source")), 7)
        self.assertEqual(len(self.gateway.events), 4)

    def test_repeated_pagination_token_fails_instead_of_hanging(self):
        class Broken:
            def call(self, operation, **kwargs):
                return {"Contents": [], "IsTruncated": True, "NextContinuationToken": "same"}
        with self.assertRaisesRegex(RuntimeError, "Repeated"):
            Workflow(Gateway(Broken())).objects("bucket")

    def test_discovery_respects_tags_and_namespace(self):
        self.seed(0)
        for bucket in ("test-source", "unrelated-source"):
            if bucket.startswith("unrelated"):
                self.backend.call("create_bucket", Bucket=bucket)
            self.backend.call("put_bucket_tagging", Bucket=bucket,
                Tagging={"TagSet": [{"Key": "rehearsal:backup", "Value": "enabled"}]})
        self.assertEqual(self.workflow.discover("test"), ["test-source"])

    def test_discovery_denial_is_not_silently_treated_as_no_tags(self):
        self.seed(0)
        self.gateway.faults.append(Fault("get_bucket_tagging", "AccessDenied"))
        with self.assertRaises(ApiError):
            self.workflow.discover("test")

    def test_transient_error_retries_with_bounded_backoff(self):
        self.seed(1)
        self.gateway.faults.append(Fault("get_object", "SlowDown", 2))
        self.assertEqual(self.workflow.read("test-source", "0"), b"object-0")
        self.assertEqual(self.delays, [0.05, 0.1])
        self.assertEqual(self.workflow.retries, 2)

    def test_permanent_error_never_retries(self):
        self.seed(1)
        self.gateway.faults.append(Fault("get_object", "AccessDenied", 10))
        with self.assertRaises(ApiError):
            self.workflow.read("test-source", "0")
        self.assertEqual(self.delays, [])
        self.assertEqual(self.gateway.faults[0].remaining, 9)

    def test_unsupported_operation_is_not_a_pass(self):
        self.seed(1)
        self.gateway.faults.append(Fault("list_objects_v2", "NotImplemented"))
        with self.assertRaises(ApiError):
            self.workflow.backup(["test-source"], "test-archive")

    def test_copy_success_with_changed_bytes_is_detected(self):
        self.seed(1)
        original_call = self.backend.call
        def corrupt(operation, **kwargs):
            result = original_call(operation, **kwargs)
            if operation == "copy_object":
                self.backend.buckets[kwargs["Bucket"]]["objects"][kwargs["Key"]] = b"changed"
            return result
        self.backend.call = corrupt
        result = self.workflow.backup(["test-source"], "test-archive")
        self.assertEqual(result["status"], "incomplete")
        self.assertEqual(result["errors"][0]["code"], "BackupIntegrityMismatch")
        self.assertEqual(result["entries"], [])

    def test_restore_of_partial_manifest_stays_incomplete(self):
        self.seed(1)
        manifest = self.workflow.backup(["test-source"], "test-archive")
        manifest["status"] = "incomplete"
        restored = self.workflow.restore(manifest, "test-archive", "test-restore")
        self.assertEqual(restored["status"], "incomplete")
        self.assertEqual(len(restored["restored"]), 1)

    def test_changed_archive_is_not_written_to_restore_target(self):
        self.seed(1)
        manifest = self.workflow.backup(["test-source"], "test-archive")
        self.backend.call("put_object", Bucket="test-archive", Key=manifest["entries"][0]["archive_key"], Body=b"bad")
        restored = self.workflow.restore(manifest, "test-archive", "test-restore")
        self.assertEqual(restored["errors"][0]["code"], "RestoreIntegrityMismatch")
        self.assertEqual(self.backend.buckets["test-restore"]["objects"], {})

    def test_stream_is_closed_after_read(self):
        stream = io.BytesIO(b"test")
        class Backend:
            def call(self, *args, **kwargs):
                return {"Body": stream}
        self.assertEqual(Workflow(Gateway(Backend())).read("x", "y"), b"test")
        self.assertTrue(stream.closed)

    def test_reports_escape_untrusted_text_and_preserve_evidence(self):
        import json
        import xml.etree.ElementTree as ET
        report = run_suite(self.backend, backend_name="offline fixture")
        report["scenarios"][0]["title"] = "<script>alert('x')</script>"
        with temporary_output() as folder:
            write_reports(report, folder)
            page = (Path(folder) / "report.html").read_text(encoding="utf-8")
            self.assertNotIn("<script>", page)
            self.assertIn("&lt;script&gt;", page)
            self.assertEqual(json.loads((Path(folder) / "report.json").read_text())["total"], 6)
            self.assertEqual(ET.parse(Path(folder) / "junit.xml").getroot().get("failures"), "0")


if __name__ == "__main__":
    unittest.main()
