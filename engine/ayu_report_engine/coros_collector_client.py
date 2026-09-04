"""Authenticated client for the Phase 6 COROS Daily Bundle endpoint."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import json
import math
import os
import socket
import time
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from .bundle import validate_coros_bundle
from .errors import SchemaValidationError
from .identity import normalize_run_id

COLLECTOR_PATH = "/internal/coros/daily-bundle"
DEFAULT_TIMEOUT_SECONDS = 90.0
USER_AGENT = "ayu-running-hub-production-collector"
SAFE_COLLECTOR_ERROR_CODES = frozenset(
    {
        "COROS_ACTIVITY_NOT_FOUND",
        "COROS_ACTIVITY_AMBIGUOUS",
        "COROS_ACTIVITY_ID_MISSING",
        "COROS_BUNDLE_INVALID",
        "COROS_REQUIRED_TOOL_MISSING",
        "COROS_MCP_CALL_FAILED",
        "COROS_MCP_UNAVAILABLE",
        "COROS_REAUTH_REQUIRED",
    }
)


class CollectorError(RuntimeError):
    """Safe collector failure that never includes provider response bodies."""

    def __init__(
        self,
        message: str,
        *,
        category: str,
        status_code: int | None = None,
        code: str | None = None,
    ) -> None:
        super().__init__(message)
        self.category = category
        self.status_code = status_code
        self.code = code


@dataclass(frozen=True)
class CollectorConfig:
    """Runtime-only collector settings; the shared secret is never repr'd."""

    base_url: str
    shared_secret: str | None
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        if not isinstance(self.base_url, str) or not self.base_url.strip():
            raise ValueError("PHASE6_COLLECTOR_URL is required")
        parsed = urlsplit(self.base_url.strip())
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("PHASE6_COLLECTOR_URL must use HTTPS")
        if parsed.query or parsed.fragment:
            raise ValueError("PHASE6_COLLECTOR_URL must not include a query or fragment")
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (int, float))
            or not math.isfinite(float(self.timeout_seconds))
            or self.timeout_seconds <= 0
        ):
            raise ValueError("collector timeout_seconds must be positive")

    @classmethod
    def from_env(cls) -> "CollectorConfig":
        raw_timeout = os.getenv("PHASE6_COLLECTOR_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT_SECONDS)).strip()
        try:
            timeout = float(raw_timeout)
        except ValueError as exc:
            raise ValueError("PHASE6_COLLECTOR_TIMEOUT_SECONDS must be a number") from exc
        return cls(
            base_url=os.getenv("PHASE6_COLLECTOR_URL", ""),
            shared_secret=os.getenv("AYU_COLLECTOR_SHARED_SECRET", "").strip() or None,
            timeout_seconds=timeout,
        )

    def __repr__(self) -> str:
        secret_state = "configured" if self.shared_secret else "missing"
        return (
            "CollectorConfig(base_url=%r, shared_secret=<%s>, timeout_seconds=%r)"
            % (self.base_url, secret_state, self.timeout_seconds)
        )


def canonical_request_body(run_id: object, request_id: object) -> tuple[str, str, str]:
    """Return the exact body and normalized identities used for signing."""

    normalized_run_id = normalize_run_id(run_id)
    if not isinstance(request_id, str) or not request_id.strip() or len(request_id) > 128:
        raise ValueError("request_id must be a non-empty string of at most 128 characters")
    normalized_request_id = request_id.strip()
    body = json.dumps(
        {"requestId": normalized_request_id, "runId": normalized_run_id},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return body, normalized_run_id, normalized_request_id


def signing_payload(
    timestamp: int,
    request_id: str,
    run_id: str,
    method: str,
    path: str,
    body: str,
) -> str:
    body_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()
    return "\n".join(
        [str(timestamp), request_id, run_id, method.upper(), path, body_hash]
    )


def _status_category(status: int) -> str:
    if status in {401, 403}:
        return "authentication"
    if status == 404:
        return "not_found"
    if status == 408:
        return "timeout"
    if status == 429:
        return "rate_limit"
    if status >= 500:
        return "server"
    if status == 400:
        return "bad_request"
    return "http_error"


def _safe_error_code(raw: bytes) -> str | None:
    """Parse only the Worker-owned allowlisted error code, never the body text."""

    try:
        value = json.loads(raw[:4096].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict):
        return None
    code = value.get("error")
    return code if isinstance(code, str) and code in SAFE_COLLECTOR_ERROR_CODES else None


def _category_for_code(status: int, code: str | None) -> str:
    if code == "COROS_ACTIVITY_NOT_FOUND":
        return "activity_not_found"
    if code == "COROS_ACTIVITY_AMBIGUOUS":
        return "ambiguous_activity"
    return _status_category(status)


def _response_status(response: Any) -> int:
    status = getattr(response, "status", None)
    if isinstance(status, int):
        return status
    status_code = getattr(response, "status_code", None)
    if isinstance(status_code, int):
        return status_code
    raise CollectorError("COROS collector returned no HTTP status", category="malformed_response")


def fetch_coros_daily_bundle(
    run_id: object,
    request_id: object,
    *,
    config: CollectorConfig | None = None,
    timestamp: int | None = None,
    clock: Callable[[], float] = time.time,
    opener: Callable[..., Any] = urlopen,
) -> dict[str, Any]:
    """Fetch and validate one COROS Daily Bundle over the signed HTTPS boundary."""

    active_config = config or CollectorConfig.from_env()
    if not active_config.shared_secret:
        raise CollectorError(
            "COROS collector shared secret is not configured",
            category="configuration",
        )
    body, normalized_run_id, normalized_request_id = canonical_request_body(run_id, request_id)
    signed_at = int(clock()) if timestamp is None else timestamp
    if not isinstance(signed_at, int) or isinstance(signed_at, bool) or signed_at < 0:
        raise ValueError("collector timestamp must be a non-negative integer")
    base_url = active_config.base_url.rstrip("/")
    url = base_url + COLLECTOR_PATH
    signature = hmac.new(
        active_config.shared_secret.encode("utf-8"),
        signing_payload(
            signed_at,
            normalized_request_id,
            normalized_run_id,
            "POST",
            COLLECTOR_PATH,
            body,
        ).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    request = Request(
        url,
        data=body.encode("utf-8"),
        method="POST",
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
            "x-ayu-timestamp": str(signed_at),
            "x-ayu-request-id": normalized_request_id,
            "x-ayu-run-id": normalized_run_id,
            "x-ayu-signature": signature,
        },
    )
    try:
        with opener(request, timeout=active_config.timeout_seconds) as response:
            status = _response_status(response)
            raw = response.read()
    except HTTPError as exc:
        code = None
        try:
            code = _safe_error_code(exc.read(4096))
        except Exception:
            pass
        raise CollectorError(
            f"COROS collector returned HTTP {exc.code}",
            category=_category_for_code(exc.code, code),
            status_code=exc.code,
            code=code,
        ) from None
    except (TimeoutError, socket.timeout):
        raise CollectorError("COROS collector timed out", category="timeout") from None
    except (URLError, OSError):
        raise CollectorError("COROS collector network request failed", category="network") from None

    if status < 200 or status >= 300:
        code = _safe_error_code(raw)
        raise CollectorError(
            f"COROS collector returned HTTP {status}",
            category=_category_for_code(status, code),
            status_code=status,
            code=code,
        )
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise CollectorError("COROS collector response was not valid JSON", category="malformed_response") from None
    if not isinstance(value, dict):
        raise CollectorError("COROS collector response was not an object", category="malformed_response")
    try:
        validate_coros_bundle(value)
    except SchemaValidationError as exc:
        raise CollectorError("COROS Daily Bundle failed validation", category="bundle_validation") from exc
    if value.get("runId") != normalized_run_id:
        raise CollectorError("COROS Daily Bundle run identity mismatch", category="bundle_validation")
    return value


def fetch_coros_daily_bundle_from_env(
    run_id: object,
    request_id: object,
    *,
    opener: Callable[..., Any] = urlopen,
) -> dict[str, Any]:
    """Convenience entry point used by production scripts."""

    return fetch_coros_daily_bundle(run_id, request_id, opener=opener)
