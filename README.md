# AWS Backup Rehearsal

[![Pilot verification](https://github.com/liorma6/aws-backup-rehearsal/actions/workflows/pilot.yml/badge.svg)](https://github.com/liorma6/aws-backup-rehearsal/actions/workflows/pilot.yml)

**A small, inspectable pilot for rehearsing S3 backup workflow failures on the official AWS Emulator.**

Discover tagged synthetic resources, copy and verify five small objects, restore them, and test how the application handles failure. Each run produces an HTML evidence report, JSON request trace, Markdown summary and JUnit XML.

Independent prototype by **Lior Mashiach**. Not affiliated with, commissioned by, or integrated with AWS or Eon. No customer data, Eon code, or Eon APIs are included. This is a test harness and example workflow, not an AWS replica or production backup product.

## Six scenarios

| Scenario | Expected application behavior | Fault mechanism |
|---|---|---|
| Tagged discovery + round trip | Select only the tagged bucket; restore all five objects with matching SHA-256 hashes | Normal backend requests |
| Transient throttling | Retry once and complete | Inject one `SlowDown` before a copy call |
| Persistent throttling | Stop after three attempts | Inject three `SlowDown` responses before listing objects |
| Source disappears | Mark the backup incomplete, preserve the missing-object evidence | Actually delete a synthetic object after inventory |
| Access denied | Do not retry the permanent failure or report success | Inject `AccessDenied` on five copy calls |
| Corrupt archive | Detect mismatched bytes and exclude the damaged object from restore | Actually overwrite one synthetic archive object |

A **PASS** for a negative scenario means the application caught the expected failure. It does **not** mean that the failed backup was successful. Injected errors are clearly identified in the request trace; they do not validate IAM enforcement or native emulator fault behavior.

## Try it without dependencies

Python 3.12+:

```sh
python -m unittest discover -s tests -v
python -m rehearsal --backend fixture --output reports/fixture
```

Open `reports/fixture/report.html`. This explicitly labeled **offline fixture** exercises the application and report; it is **not AWS Emulator validation**. There is no silent fallback to the fixture.

## Run with the official AWS Emulator

1. Install [AWS Emulator](https://docs.aws.amazon.com/emulator/latest/userguide/getting-started-linux.html) on Linux, or follow the [official Docker guide](https://docs.aws.amazon.com/emulator/latest/userguide/getting-started-docker.html) on Windows/macOS.
2. Install the Python SDK in a virtual environment:

```sh
python -m venv .venv
# Linux/macOS: source .venv/bin/activate
# Windows PowerShell: .\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

3. On Linux, run the managed demonstration. It starts the installed emulator on port 9397, waits for a verified TLS health response, executes all scenarios twice, checks semantic repeatability, and stops its own process:

```sh
python scripts/run_with_emulator.py
```

Or attach to an emulator you started yourself:

```sh
aws-emulator -p 9297 --telemetry off
# In another terminal:
python -m rehearsal --endpoint https://127.0.0.1:9297 --state-dir ~/.aws/emulator/9297
```

In Windows PowerShell, use `--state-dir "$env:USERPROFILE\.aws\emulator\9297"` or the corresponding mounted host directory from your Docker setup.

The adapter reads the emulator's `emulator_credentials` and `ca.pem` explicitly, verifies TLS, uses path-style S3 addressing, disables SDK retries so application retries are measurable, and rejects endpoints outside `https://127.0.0.1:<port>`. Real cloud endpoints are intentionally unsupported. Do not supply production credentials or data.

Each scenario creates a unique `rehearsal-…` namespace and cleans up only the buckets it created. State is also ephemeral in AWS Emulator. In case of an interrupted run, stop your disposable emulator to discard its state.

## CI and evidence

[GitHub Actions](https://github.com/liorma6/aws-backup-rehearsal/actions/workflows/pilot.yml) runs two separate jobs:

- **unit:** behavior tests and the explicitly labeled offline fixture.
- **emulator:** install the official AWS package with GPG signature and publishing-key fingerprint checks; run the six scenarios twice on that binary.

Download `aws-emulator-evidence` from a completed run for the actual HTML/JSON/JUnit output, build version, package SHA-256 and repeatability result. A failed or unavailable emulator job is a failed validation, never an implied pass. The installer uses AWS's latest signed package; the build identity is recorded for each execution. Later releases can behave differently.

| Output | Purpose |
|---|---|
| `report.html` | Standalone visual report with expandable request evidence |
| `report.json` | Scenario checks, retries, manifests, request outcomes and timings |
| `report.md` | Readable summary for reviewers and CI |
| `junit.xml` | Machine-readable test result |
| `repeatability.json` | Two runs agree on checks and retry counts |

Durations are single-machine measurements including synthetic setup and cleanup, **not** cloud benchmarks or demonstrated cost savings.

## Boundaries

- Five small synthetic objects per scenario; the example reads each into memory. Not a scalable backup engine.
- Object keys, sizes and SHA-256 content only. No preservation of all metadata, versions, ACLs, encryption configuration or retention semantics.
- No atomic point-in-time snapshot guarantee; concurrent production changes are out of scope.
- No EBS/RDS, KMS, IAM correctness, cross-account, cross-region, multipart or production durability coverage.
- No real-AWS parity comparison. The official emulator itself documents fidelity and security limitations.
- The workflow can be adapted to a partner's narrow test path only after reviewing its API requirements and integration surface.

See [PILOT.md](PILOT.md) for an explicitly proposed evaluation, acceptance criteria and the open questions before any commercial engagement.

## Layout

```text
rehearsal/backend.py    Explicit boto3 adapter and offline fixture
rehearsal/workflow.py   Discovery, retries, manifests and verification
rehearsal/runner.py     Six synthetic scenarios and scoped cleanup
rehearsal/report.py     Portable evidence renderers
tests/                 Behavioral and safety regression tests
scripts/               Official emulator installation and managed execution
```

## Primary references

- [AWS Emulator overview and limitations](https://docs.aws.amazon.com/emulator/latest/userguide/what-is-service.html)
- [Fidelity and coverage](https://docs.aws.amazon.com/emulator/latest/userguide/fidelity.html)
- [Security limitations](https://docs.aws.amazon.com/emulator/latest/userguide/security.html)
- [SDK connection, authentication and certificates](https://docs.aws.amazon.com/emulator/latest/userguide/point-sdk-to-emulator.html)
- [Official package installation and signature verification](https://docs.aws.amazon.com/emulator/latest/userguide/getting-started-linux.html)

Copyright © 2026 Lior Mashiach. Public source is provided for inspection; no commercial license is granted by this repository.
