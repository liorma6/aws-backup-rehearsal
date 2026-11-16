"""SDK adapter, local-only connection policy, and an explicit offline fixture."""
from __future__ import annotations

import configparser
import io
from pathlib import Path
from urllib.parse import urlsplit


class ApiError(Exception):
    def __init__(self, code: str, operation: str):
        self.code, self.operation = code, operation
        super().__init__(f"{operation}: {code}")


def validate_endpoint(endpoint: str) -> str:
    """Accept one literal loopback address; never resolve a user-supplied host."""
    url = urlsplit(endpoint)
    if (url.scheme != "https" or url.hostname != "127.0.0.1"
            or url.username or url.password or url.path not in ("", "/")
            or url.query or url.fragment or not url.port):
        raise ValueError("Use https://127.0.0.1:<port>; cloud and remote endpoints are refused.")
    return f"https://127.0.0.1:{url.port}"


class BotoBackend:
    def __init__(self, endpoint: str, state_dir: Path):
        endpoint = validate_endpoint(endpoint)
        state_dir = state_dir.expanduser().resolve()
        parser = configparser.ConfigParser()
        credentials = state_dir / "emulator_credentials"
        ca = state_dir / "ca.pem"
        if not credentials.is_file() or not ca.is_file():
            raise ValueError("Missing emulator_credentials or ca.pem in --state-dir. Start AWS Emulator first.")
        parser.read(credentials, encoding="utf-8")
        section = parser["default"]
        import boto3
        from botocore.config import Config
        # Explicit credentials: no profile, environment, container or metadata lookup.
        session = boto3.Session(
            aws_access_key_id=section["aws_access_key_id"],
            aws_secret_access_key=section["aws_secret_access_key"],
            region_name="us-east-1",
        )
        self.client = session.client(
            "s3", endpoint_url=endpoint, verify=str(ca),
            config=Config(
                signature_version="s3v4", s3={"addressing_style": "path"},
                inject_host_prefix=False, proxies={},
                retries={"total_max_attempts": 1, "mode": "standard"},
                connect_timeout=3, read_timeout=5,
            ),
        )
        # A redirect must never send a signed request away from the local emulator.
        def guard(request, **_):
            url = urlsplit(request.url)
            if f"{url.scheme}://{url.netloc}" != endpoint:
                raise ValueError("Blocked a request outside the configured emulator endpoint.")
        self.client.meta.events.register("before-send.s3", guard)

    def call(self, operation: str, **kwargs):
        try:
            return getattr(self.client, operation)(**kwargs)
        except Exception as exc:
            response = getattr(exc, "response", {})
            code = response.get("Error", {}).get("Code")
            if code:
                raise ApiError(code, operation) from exc
            raise


class FixtureBackend:
    """Small test double. It is NOT AWS Emulator or evidence of AWS compatibility."""
    def __init__(self):
        self.buckets: dict[str, dict] = {}

    def call(self, operation: str, **kwargs):
        if operation == "create_bucket":
            name = kwargs["Bucket"]
            if name in self.buckets:
                raise ApiError("BucketAlreadyOwnedByYou", operation)
            self.buckets[name] = {"tags": [], "objects": {}}
            return {}
        if operation == "list_buckets":
            return {"Buckets": [{"Name": name} for name in sorted(self.buckets)]}
        name = kwargs["Bucket"]
        if name not in self.buckets:
            raise ApiError("NoSuchBucket", operation)
        bucket = self.buckets[name]
        objects = bucket["objects"]
        if operation == "put_bucket_tagging":
            bucket["tags"] = kwargs["Tagging"]["TagSet"]
        elif operation == "get_bucket_tagging":
            if not bucket["tags"]:
                raise ApiError("NoSuchTagSet", operation)
            return {"TagSet": bucket["tags"]}
        elif operation == "put_object":
            objects[kwargs["Key"]] = bytes(kwargs["Body"])
        elif operation == "get_object":
            key = kwargs["Key"]
            if key not in objects:
                raise ApiError("NoSuchKey", operation)
            return {"Body": io.BytesIO(objects[key])}
        elif operation == "copy_object":
            source = kwargs["CopySource"]
            source_bucket = self.buckets.get(source["Bucket"])
            if source_bucket is None or source["Key"] not in source_bucket["objects"]:
                raise ApiError("NoSuchKey", operation)
            objects[kwargs["Key"]] = source_bucket["objects"][source["Key"]]
        elif operation == "list_objects_v2":
            keys = sorted(k for k in objects if k.startswith(kwargs.get("Prefix", "")))
            start = int(kwargs.get("ContinuationToken", "0"))
            end = start + kwargs.get("MaxKeys", 1000)
            result = {"Contents": [{"Key": k, "Size": len(objects[k])} for k in keys[start:end]],
                      "IsTruncated": end < len(keys)}
            if result["IsTruncated"]:
                result["NextContinuationToken"] = str(end)
            return result
        elif operation == "delete_object":
            objects.pop(kwargs["Key"], None)
        elif operation == "delete_bucket":
            if objects:
                raise ApiError("BucketNotEmpty", operation)
            del self.buckets[name]
        else:
            raise ApiError("NotImplemented", operation)
        return {}
