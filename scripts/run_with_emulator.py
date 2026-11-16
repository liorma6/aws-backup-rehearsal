"""Start an installed official emulator, wait for TLS health, run twice, stop it."""
import json
import os
from pathlib import Path
import signal
import ssl
import subprocess
import sys
import time
import urllib.request


def main():
    output = Path("reports/emulator")
    output.mkdir(parents=True, exist_ok=True)
    state = Path.home() / ".aws/emulator/9397"
    # Fail if another emulator owns this port/state; do not attach to or stop it.
    if (state / "emulator_credentials").exists():
        raise RuntimeError("Port 9397 state already exists. Choose a clean environment.")
    version = subprocess.check_output(["aws-emulator", "-v"], text=True).strip()
    (output / "emulator-version.txt").write_text(version + "\n", encoding="utf-8")
    env = dict(os.environ, EMULATOR_TELEMETRY="off")
    for key in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN", "AWS_PROFILE"):
        env.pop(key, None)
    log = open("reports/emulator-process.log", "w", encoding="utf-8")
    proc = subprocess.Popen(["aws-emulator", "-p", "9397", "--telemetry", "off"], env=env,
                            stdout=log, stderr=subprocess.STDOUT)
    try:
        ready = False
        for _ in range(50):
            if proc.poll() is not None:
                raise RuntimeError(f"Emulator exited before health check: {proc.returncode}")
            if (state / "ca.pem").exists() and (state / "emulator_credentials").exists():
                try:
                    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),
                        urllib.request.HTTPSHandler(context=ssl.create_default_context(cafile=str(state / "ca.pem"))))
                    with opener.open("https://127.0.0.1:9397/__admin/health", timeout=1) as response:
                        ready = response.status == 200 and response.read().strip() == b"ok"
                    if ready:
                        break
                except (OSError, ValueError):
                    pass
            time.sleep(0.5)
        if not ready:
            raise RuntimeError("Emulator did not become ready within 25 seconds")
        codes = []
        for iteration in (1, 2):
            codes.append(subprocess.call([sys.executable, "-m", "rehearsal", "--endpoint", "https://127.0.0.1:9397",
                "--state-dir", str(state), "--output", str(output / f"run-{iteration}"),
                "--emulator-version", version], env=env))
        if any(codes):
            return 1
        reports = [json.loads((output / f"run-{i}" / "report.json").read_text()) for i in (1, 2)]
        signature = lambda report: [(s["id"], s["passed"], s["checks"], s["retries"]) for s in report["scenarios"]]
        if signature(reports[0]) != signature(reports[1]):
            raise RuntimeError("The two emulator runs disagree")
        (output / "repeatability.json").write_text(json.dumps({"runs": 2, "same_expectations": True,
            "run_ids": [r["run_id"] for r in reports], "note": "Semantic repeatability; durations vary."}, indent=2))
        return 0
    finally:
        proc.send_signal(signal.SIGTERM) if proc.poll() is None else None
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        log.close()


if __name__ == "__main__":
    raise SystemExit(main())
