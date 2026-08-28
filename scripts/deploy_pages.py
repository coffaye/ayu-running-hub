"""Dispatch and verify the running_page GitHub Pages workflow."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import time
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


GITHUB_API = "https://api.github.com"
PAGES_ORIGIN = "https://coffaye.github.io/running_page"
USER_AGENT = "ayu-running-hub-pages-dispatcher"
REPORT_URL_PATTERN = re.compile(r"^reports/daily/\d{4}-\d{2}-\d{2}/\d+\.html$")


class GithubApiError(RuntimeError):
    """A safe, status-only GitHub API failure."""

    def __init__(self, operation: str, status: int | None = None) -> None:
        self.operation = operation
        self.status = status
        suffix = f" ({status})" if status is not None else ""
        super().__init__(f"{operation} failed{suffix}")


def _json_request(
    method: str,
    url: str,
    token: str,
    payload: Mapping[str, Any] | None = None,
    opener: Callable[..., Any] = urlopen,
) -> Mapping[str, Any]:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(
        url,
        data=body,
        method=method,
        headers={
            "accept": "application/vnd.github+json",
            "content-type": "application/json",
            "x-github-api-version": "2022-11-28",
            "user-agent": USER_AGENT,
            "authorization": f"Bearer {token}",
        },
    )
    try:
        with opener(request, timeout=30) as response:
            raw = response.read()
            if not raw:
                return {}
            value = json.loads(raw.decode("utf-8"))
    except HTTPError as exc:
        raise GithubApiError(f"GitHub {method} {url.rsplit('/', 1)[-1]}", exc.code) from None
    except (OSError, URLError, json.JSONDecodeError) as exc:
        raise GithubApiError(f"GitHub {method} request") from exc
    if not isinstance(value, Mapping):
        raise GithubApiError(f"GitHub {method} response")
    return value


def dispatch_pages_workflow(
    token: str,
    *,
    repository: str = "coffaye/running_page",
    workflow: str = "gh-pages.yml",
    ref: str = "master",
    opener: Callable[..., Any] = urlopen,
) -> int:
    if ref != "master":
        raise ValueError("Pages dispatch ref must be master")
    endpoint = (
        f"{GITHUB_API}/repos/{repository}/actions/workflows/{workflow}/dispatches"
        "?return_run_details=true"
    )
    response = _json_request(
        "POST",
        endpoint,
        token,
        {"ref": ref, "inputs": {"save_data_in_github_cache": False, "data_cache_prefix": "track_data"}},
        opener,
    )
    nested = response.get("workflow_run")
    workflow_run_id = nested.get("id") if isinstance(nested, Mapping) else response.get("workflow_run_id")
    if not isinstance(workflow_run_id, int) or workflow_run_id <= 0:
        raise GithubApiError("Pages workflow dispatch returned no workflow run ID")
    return workflow_run_id


def wait_for_pages(
    token: str,
    workflow_run_id: int,
    *,
    repository: str = "coffaye/running_page",
    max_wait_seconds: int = 900,
    poll_seconds: int = 5,
    sleep: Callable[[float], None] = time.sleep,
    opener: Callable[..., Any] = urlopen,
) -> Mapping[str, Any]:
    deadline = time.monotonic() + max_wait_seconds
    endpoint = f"{GITHUB_API}/repos/{repository}/actions/runs/{workflow_run_id}"
    while True:
        value = _json_request("GET", endpoint, token, opener=opener)
        status = value.get("status")
        conclusion = value.get("conclusion")
        if status == "completed":
            if conclusion == "success":
                return value
            raise GithubApiError(f"Pages workflow concluded {conclusion or 'without success'}")
        if time.monotonic() >= deadline:
            raise GithubApiError("Pages workflow timed out")
        sleep(poll_seconds)


def _fetch_bytes(url: str, opener: Callable[..., Any] = urlopen) -> bytes:
    request = Request(url, headers={"accept": "application/json, text/html", "user-agent": USER_AGENT})
    try:
        with opener(request, timeout=30) as response:
            if getattr(response, "status", 200) != 200:
                raise GithubApiError("live Pages request", int(response.status))
            return response.read()
    except HTTPError as exc:
        raise GithubApiError("live Pages request", exc.code) from None
    except (OSError, URLError) as exc:
        raise GithubApiError("live Pages request") from exc


def verify_live_report(
    run_id: str,
    *,
    expected_engine_commit: str,
    local_report: Path,
    pages_origin: str = PAGES_ORIGIN,
    attempts: int = 12,
    retry_seconds: int = 10,
    sleep: Callable[[float], None] = time.sleep,
    opener: Callable[..., Any] = urlopen,
) -> dict[str, Any]:
    if not local_report.is_file():
        raise ValueError("local generated report is missing")
    normalized = str(run_id).strip()
    if not normalized.isdigit() or int(normalized) <= 0:
        raise ValueError("run_id must contain positive decimal digits only")
    local_hash = hashlib.sha256(local_report.read_bytes()).hexdigest()
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            cache_buster = urlencode({"ayu_run_id": normalized, "t": str(time.time_ns())})
            manifest_url = f"{pages_origin.rstrip('/')}/reports/manifest.json?{cache_buster}"
            manifest = json.loads(_fetch_bytes(manifest_url, opener).decode("utf-8"))
            if not isinstance(manifest, Mapping) or not isinstance(manifest.get("reports"), Mapping):
                raise ValueError("live manifest is invalid")
            entry = manifest["reports"].get(normalized)
            if not isinstance(entry, Mapping):
                raise ValueError("live manifest entry is missing")
            report_url = entry.get("url")
            if not isinstance(report_url, str) or not REPORT_URL_PATTERN.fullmatch(report_url):
                raise ValueError("live report URL is invalid")
            if str(entry.get("runId")) != normalized:
                raise ValueError("live manifest runId mismatch")
            if expected_engine_commit and entry.get("engineCommit") != expected_engine_commit:
                raise ValueError("live manifest engineCommit mismatch")
            report_url_full = f"{pages_origin.rstrip('/')}/{report_url}"
            live_html = _fetch_bytes(f"{report_url_full}?{cache_buster}", opener)
            live_hash = hashlib.sha256(live_html).hexdigest()
            if live_hash != local_hash:
                raise ValueError("live report does not match generated artifact")
            return {
                "manifestUrl": manifest_url,
                "reportUrl": report_url_full,
                "generatedAt": entry.get("generatedAt"),
                "engineCommit": entry.get("engineCommit"),
                "htmlSha256": live_hash,
                "verificationAttempt": attempt,
            }
        except (GithubApiError, ValueError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt < attempts:
                sleep(retry_seconds)
    raise RuntimeError(f"live report verification failed after {attempts} attempts") from last_error


def deploy_and_verify(
    token: str,
    *,
    run_id: str,
    expected_engine_commit: str,
    local_report: Path,
    repository: str = "coffaye/running_page",
    workflow: str = "gh-pages.yml",
    max_wait_seconds: int = 900,
    opener: Callable[..., Any] = urlopen,
) -> dict[str, Any]:
    pages_run_id = dispatch_pages_workflow(token, repository=repository, workflow=workflow, opener=opener)
    run = wait_for_pages(token, pages_run_id, repository=repository, max_wait_seconds=max_wait_seconds, opener=opener)
    live = verify_live_report(
        run_id,
        expected_engine_commit=expected_engine_commit,
        local_report=local_report,
        opener=opener,
    )
    return {
        "pagesWorkflowRunId": pages_run_id,
        "pagesStatus": run.get("status"),
        "pagesConclusion": run.get("conclusion"),
        **live,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Dispatch and verify the running_page Pages workflow")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--engine-commit", required=True)
    parser.add_argument("--local-report", type=Path, required=True)
    parser.add_argument("--token-env", default="RUNNING_PAGE_WRITE_TOKEN")
    parser.add_argument("--repository", default="coffaye/running_page")
    parser.add_argument("--workflow", default="gh-pages.yml")
    parser.add_argument("--max-wait-seconds", type=int, default=900)
    args = parser.parse_args(argv)
    token = os.environ.get(args.token_env, "")
    if not token:
        print(json.dumps({"status": "failure", "error": "Pages write token is not configured"}))
        return 1
    try:
        result = deploy_and_verify(
            token,
            run_id=args.run_id,
            expected_engine_commit=args.engine_commit,
            local_report=args.local_report,
            repository=args.repository,
            workflow=args.workflow,
            max_wait_seconds=args.max_wait_seconds,
        )
    except Exception as exc:
        print(json.dumps({"status": "failure", "error": str(exc)}))
        return 1
    print(json.dumps({"status": "success", **result}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
