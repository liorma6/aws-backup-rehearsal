"""Six repeatable scenarios against synthetic resources owned by one run."""
from __future__ import annotations

import json
import platform
import time
import uuid
from datetime import datetime, timezone
from .workflow import Fault, Gateway, Workflow

SCENARIOS = (
    ("round_trip", "Tagged discovery and verified restore", "5 objects restored; untagged bucket excluded"),
    ("transient_retry", "Transient throttling", "One injected SlowDown; retry then restore 5 objects"),
    ("retry_exhaustion", "Persistent throttling", "Stop after 3 attempts; no success claim"),
    ("source_disappears", "Source object disappears", "Native delete after listing; incomplete backup reported"),
    ("access_denied", "Denied request handling", "Injected AccessDenied is not retried; incomplete backup"),
    ("corrupt_archive", "Archive integrity failure", "Native overwrite of one archive object; corruption detected"),
)


def run_scenario(backend, scenario, index, run_id):
    name, title, expected = scenario
    namespace = f"rehearsal-{run_id}-{index}"
    source, skipped, archive, target = [namespace + "-" + suffix for suffix in ("source", "skip", "archive", "restore")]
    gateway = Gateway(backend)
    workflow = Workflow(gateway)
    created, checks, cleanup_errors = [], [], []
    start = time.perf_counter()
    result = {"id": name, "title": title, "expected": expected, "checks": checks,
              "fault_boundary": "application SDK-call wrapper; not AWS service or IAM behavior",
              "events": gateway.events, "cleanup_errors": cleanup_errors}

    def check(label, condition):
        checks.append({"label": label, "passed": bool(condition)})

    try:
        for bucket in (source, skipped, archive, target):
            gateway.call("create_bucket", Bucket=bucket)
            created.append(bucket)
        gateway.call("put_bucket_tagging", Bucket=source,
                     Tagging={"TagSet": [{"Key": "rehearsal:backup", "Value": "enabled"}]})
        for i in range(5):
            payload = json.dumps({"synthetic": True, "record": i, "value": f"example-{i}"}, sort_keys=True).encode()
            gateway.call("put_object", Bucket=source, Key=f"records/{i}.json", Body=payload)
        gateway.call("put_object", Bucket=skipped, Key="excluded.txt", Body=b"synthetic excluded object")
        selected = workflow.discover(namespace)
        check("Only the tagged source is selected", selected == [source])
        result["selected_buckets"] = selected
        if name == "transient_retry":
            gateway.faults.append(Fault("copy_object", "SlowDown"))
        elif name == "retry_exhaustion":
            gateway.faults.append(Fault("list_objects_v2", "SlowDown", 3))
        elif name == "access_denied":
            gateway.faults.append(Fault("copy_object", "AccessDenied", 5))

        def delete_after_inventory(bucket, inventory):
            gateway.call("delete_object", Bucket=bucket, Key=inventory[0]["Key"])

        if name == "retry_exhaustion":
            from .backend import ApiError
            try:
                workflow.backup(selected, archive)
                check("Persistent failure stops the workflow", False)
            except ApiError as exc:
                check("Failure retains the throttling code", exc.code == "SlowDown")
                check("Retry budget is bounded to three attempts", workflow.retries == 2)
                check("Exactly three calls were injected", sum(e["origin"] == "injected" for e in gateway.events) == 3)
            result["workflow_status"] = "incomplete"
        else:
            manifest = workflow.backup(selected, archive,
                after_inventory=delete_after_inventory if name == "source_disappears" else None)
            result["manifest"] = manifest
            if name == "corrupt_archive":
                gateway.call("put_object", Bucket=archive, Key=manifest["entries"][0]["archive_key"],
                             Body=b"synthetic deliberate corruption")
            restored = workflow.restore(manifest, archive, target)
            result["restore"] = restored
            result["workflow_status"] = restored["status"]
            if name in ("round_trip", "transient_retry"):
                check("Backup and restore both complete", manifest["status"] == restored["status"] == "complete")
                check("All five objects are restored", len(restored["restored"]) == 5)
                check("Checksums are recorded for every object", len(manifest["entries"]) == 5)
                if name == "transient_retry":
                    check("Exactly one retry is recorded", workflow.retries == 1)
                    check("The planned fault was triggered", gateway.faults[0].remaining == 0)
            elif name == "source_disappears":
                check("Missing source fails the backup closed", manifest["status"] == "incomplete")
                check("Missing source is reported specifically", [e["code"] for e in manifest["errors"]] == ["NoSuchKey"])
                check("Four available objects restore without hiding incompleteness",
                      len(restored["restored"]) == 4 and restored["status"] == "incomplete")
            elif name == "access_denied":
                check("Denied copies are not called a successful backup", manifest["status"] == "incomplete")
                check("All five denials are recorded", len(manifest["errors"]) == 5 and all(e["code"] == "AccessDenied" for e in manifest["errors"]))
                check("Permanent denial is not retried", workflow.retries == 0)
                check("Nothing was restored", len(restored["restored"]) == 0)
            elif name == "corrupt_archive":
                check("Baseline backup was complete", manifest["status"] == "complete")
                check("Corrupt archive cannot pass restore", restored["status"] == "incomplete")
                check("Integrity error identifies the changed object",
                      [e["code"] for e in restored["errors"]] == ["RestoreIntegrityMismatch"])
                check("Only the four intact objects restore", len(restored["restored"]) == 4)
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        check("Scenario completed without an unexpected error", False)
    finally:
        # Disable planned faults before cleanup; delete only resources created here.
        gateway.faults.clear()
        for bucket in reversed(created):
            try:
                for obj in workflow.objects(bucket):
                    gateway.call("delete_object", Bucket=bucket, Key=obj["Key"])
                gateway.call("delete_bucket", Bucket=bucket)
            except Exception as exc:
                cleanup_errors.append({"bucket": bucket, "error": f"{type(exc).__name__}: {exc}"})
        check("All created resources cleaned up", not cleanup_errors)
    result.update(passed=all(c["passed"] for c in checks), retries=workflow.retries,
                  elapsed_ms=round((time.perf_counter() - start) * 1000, 2))
    return result


def run_suite(backend, *, backend_name, endpoint=None, emulator_version=None):
    start = time.perf_counter()
    run_id = uuid.uuid4().hex[:12]
    results = [run_scenario(backend, scenario, i, run_id) for i, scenario in enumerate(SCENARIOS)]
    return {"schema_version": 1, "project": "AWS Backup Rehearsal", "run_id": run_id,
            "created_at": datetime.now(timezone.utc).isoformat(), "backend": backend_name,
            "endpoint": endpoint, "emulator_version": emulator_version,
            "python": platform.python_version(), "data": "synthetic only",
            "aws_parity_verified": False, "eon_integration": False,
            "duration_ms": round((time.perf_counter() - start) * 1000, 2),
            "passed": sum(r["passed"] for r in results), "total": len(results), "scenarios": results,
            "limitations": ["No Eon code, APIs, or customer data were used.",
                "Injected errors test application handling, not emulator IAM or service fault fidelity.",
                "No real-AWS comparison, cost saving, production recovery guarantee, RPO or RTO claim.",
                "Tiny S3 objects only; no versioning, snapshots, KMS, multipart, cross-account or cross-region coverage.",
                "A green negative scenario means the application correctly detected the planned failure."]}
