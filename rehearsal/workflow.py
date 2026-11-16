"""Application workflow under test, independent of the fixture and AWS SDK."""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from .backend import ApiError


@dataclass
class Fault:
    operation: str
    code: str
    remaining: int = 1


@dataclass
class Gateway:
    backend: object
    faults: list[Fault] = field(default_factory=list)
    events: list[dict] = field(default_factory=list)

    def call(self, operation: str, **kwargs):
        event = {"operation": operation, "bucket": kwargs.get("Bucket"),
                 "key": kwargs.get("Key"), "origin": "backend", "outcome": "ok"}
        start = time.perf_counter()
        try:
            for fault in self.faults:
                if fault.operation == operation and fault.remaining > 0:
                    fault.remaining -= 1
                    event["origin"] = "injected"
                    raise ApiError(fault.code, operation)
            return self.backend.call(operation, **kwargs)
        except ApiError as exc:
            event["outcome"] = exc.code
            raise
        except Exception as exc:
            event["outcome"] = type(exc).__name__
            raise
        finally:
            event["elapsed_ms"] = round((time.perf_counter() - start) * 1000, 3)
            self.events.append(event)


class Workflow:
    RETRYABLE = {"SlowDown", "Throttling", "ServiceUnavailable", "InternalError", "RequestTimeout"}

    def __init__(self, gateway: Gateway, *, attempts: int = 3, sleep=time.sleep):
        if not 1 <= attempts <= 5:
            raise ValueError("attempts must be between 1 and 5")
        self.gateway, self.attempts, self.sleep = gateway, attempts, sleep
        self.retries = 0

    def call(self, operation, **kwargs):
        for attempt in range(self.attempts):
            try:
                return self.gateway.call(operation, **kwargs)
            except ApiError as exc:
                if exc.code not in self.RETRYABLE or attempt == self.attempts - 1:
                    raise
                self.retries += 1
                self.sleep(0.05 * (2 ** attempt))

    def _pages(self, operation, item_key, **kwargs):
        token, seen = None, set()
        for _ in range(100):
            response = self.call(operation, **kwargs, **({"ContinuationToken": token} if token else {}))
            yield from response.get(item_key, [])
            next_token = response.get("NextContinuationToken") or response.get("ContinuationToken")
            if operation == "list_objects_v2" and not response.get("IsTruncated", False):
                return
            if not next_token:
                if response.get("IsTruncated"):
                    raise RuntimeError("Truncated page without a continuation token")
                return
            if next_token in seen:
                raise RuntimeError("Repeated continuation token")
            seen.add(next_token)
            token = next_token
        raise RuntimeError("Pilot pagination limit exceeded")

    def discover(self, namespace: str):
        selected = []
        for bucket in self._pages("list_buckets", "Buckets"):
            name = bucket["Name"]
            if not name.startswith(namespace + "-"):
                continue
            try:
                tags = self.call("get_bucket_tagging", Bucket=name).get("TagSet", [])
            except ApiError as exc:
                if exc.code == "NoSuchTagSet":
                    continue
                raise
            if {t["Key"]: t["Value"] for t in tags}.get("rehearsal:backup") == "enabled":
                selected.append(name)
        return sorted(selected)

    def objects(self, bucket):
        return list(self._pages("list_objects_v2", "Contents", Bucket=bucket, MaxKeys=2))

    def read(self, bucket, key):
        body = self.call("get_object", Bucket=bucket, Key=key)["Body"]
        try:
            return body.read()
        finally:
            body.close()

    def backup(self, sources, destination, *, after_inventory=None):
        entries, errors = [], []
        for source in sources:
            inventory = self.objects(source)
            if after_inventory:
                after_inventory(source, inventory)
            for item in inventory:
                key = item["Key"]
                try:
                    original = self.read(source, key)
                    archive_key = f"{source}/{key}"
                    self.call("copy_object", Bucket=destination, Key=archive_key,
                              CopySource={"Bucket": source, "Key": key})
                    copied = self.read(destination, archive_key)
                    digest = hashlib.sha256(original).hexdigest()
                    if hashlib.sha256(copied).hexdigest() != digest:
                        errors.append({"key": key, "code": "BackupIntegrityMismatch"})
                        continue
                    entries.append({"source": source, "key": key, "archive_key": archive_key,
                                    "sha256": digest, "bytes": len(original)})
                except ApiError as exc:
                    errors.append({"key": key, "code": exc.code})
        return {"status": "complete" if not errors else "incomplete", "entries": entries, "errors": errors}

    def restore(self, manifest, archive, target):
        errors, restored = [], []
        for entry in manifest["entries"]:
            key = entry["archive_key"]
            try:
                archived = self.read(archive, key)
                if hashlib.sha256(archived).hexdigest() != entry["sha256"]:
                    errors.append({"key": entry["key"], "code": "RestoreIntegrityMismatch"})
                    continue
                self.call("copy_object", Bucket=target, Key=key,
                          CopySource={"Bucket": archive, "Key": key})
                actual = self.read(target, key)
                if hashlib.sha256(actual).hexdigest() != entry["sha256"]:
                    errors.append({"key": entry["key"], "code": "RestoreIntegrityMismatch"})
                    continue
                restored.append(key)
            except ApiError as exc:
                errors.append({"key": entry["key"], "code": exc.code})
        return {"status": "complete" if manifest["status"] == "complete" and not errors else "incomplete",
                "restored": restored, "errors": errors}
