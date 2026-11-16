import argparse
import json
import os
from pathlib import Path
from .backend import BotoBackend, FixtureBackend, validate_endpoint
from .runner import run_suite
from .report import write_reports


def main():
    parser = argparse.ArgumentParser(description="Synthetic S3 backup workflow rehearsal; local emulator only.")
    parser.add_argument("--backend", choices=("emulator", "fixture"), default="emulator")
    parser.add_argument("--endpoint", default="https://127.0.0.1:9297")
    parser.add_argument("--state-dir", type=Path, default=Path.home() / ".aws/emulator/9297")
    parser.add_argument("--output", type=Path, default=Path("reports"))
    parser.add_argument("--emulator-version", default=os.environ.get("REHEARSAL_EMULATOR_VERSION"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    try:
        if args.backend == "fixture":
            backend, name, endpoint = FixtureBackend(), "offline fixture — NOT AWS Emulator", None
        else:
            endpoint = validate_endpoint(args.endpoint)
            backend, name = BotoBackend(endpoint, args.state_dir), "AWS Emulator"
        report = run_suite(backend, backend_name=name, endpoint=endpoint,
                           emulator_version=args.emulator_version if args.backend == "emulator" else None)
        write_reports(report, args.output)
    except Exception as exc:
        failure = {"status": "blocked", "backend": args.backend, "error": f"{type(exc).__name__}: {exc}",
                   "note": "No successful emulator validation is claimed."}
        (args.output / "setup-failure.json").write_text(json.dumps(failure, indent=2), encoding="utf-8")
        print(f"BLOCKED: {failure['error']}")
        return 2
    print(f"{report['passed']}/{report['total']} scenarios passed | {name} | {report['duration_ms']} ms")
    for scenario in report["scenarios"]:
        print(f"  {'PASS' if scenario['passed'] else 'FAIL'} {scenario['id']}")
    print(f"Evidence: {args.output.resolve()}")
    return 0 if report["passed"] == report["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
