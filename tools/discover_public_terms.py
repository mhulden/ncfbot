#!/usr/bin/env python3
"""Discover every term exposed by NCF's anonymous public Banner selector."""

from __future__ import annotations

import argparse
import http.cookiejar
import json
import os
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

TOOL_VERSION = "1.0.0"
SCHEMA_VERSION = "1.0"
DEFAULT_BASE_URL = "https://banapps02.ncf.edu/StudentRegistrationSsb/ssb"
TERM_SELECTION_PATH = "/term/termSelection?mode=search"
TERM_ENDPOINT_PATH = "/classSearch/getTerms"
USER_AGENT = "ncfbot-course-data/1.0 (+https://github.com/mhulden/ncfbot)"


class BannerError(RuntimeError):
    """The public Banner service failed or returned an invalid response."""


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def atomic_write_json(path: Path, value: Any) -> None:
    atomic_write_bytes(path, (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode())


def atomic_write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    body = "".join(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n" for row in rows)
    atomic_write_bytes(path, body.encode())


class BannerSession:
    """Short-lived anonymous Banner session; cookies are never persisted."""

    def __init__(self, base_url: str = DEFAULT_BASE_URL, timeout: float = 30.0) -> None:
        parsed = urllib.parse.urlparse(base_url)
        if parsed.scheme != "https" and parsed.hostname not in {"127.0.0.1", "localhost"}:
            raise ValueError("Banner base URL must use HTTPS")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.cookie_jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cookie_jar))
        self.bootstrapped = False

    def url(self, path: str) -> str:
        return f"{self.base_url}/{path.lstrip('/')}"

    def request(
        self,
        path: str,
        *,
        query: dict[str, Any] | None = None,
        form: dict[str, Any] | None = None,
        ajax: bool = False,
        referer: str | None = None,
    ) -> tuple[bytes, str]:
        url = self.url(path)
        if query:
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode(query, doseq=True)
        data = urllib.parse.urlencode(form).encode() if form is not None else None
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "application/json, text/javascript, */*; q=0.01" if ajax else "text/html,*/*;q=0.8",
        }
        if ajax:
            headers["X-Requested-With"] = "XMLHttpRequest"
        if referer:
            headers["Referer"] = referer
        try:
            request = urllib.request.Request(url, data=data, headers=headers)
            with self.opener.open(request, timeout=self.timeout) as response:
                return response.read(), response.headers.get_content_type()
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
            raise BannerError(f"public Banner request failed for {url}: {exc}") from exc

    def get_json(self, path: str, **kwargs: Any) -> Any:
        body, _ = self.request(path, ajax=True, **kwargs)
        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            raise BannerError(f"public Banner returned non-JSON for {self.url(path)}") from exc

    def bootstrap(self) -> None:
        body, content_type = self.request(TERM_SELECTION_PATH)
        if content_type != "text/html" or b"txt_term" not in body:
            raise BannerError("public term-selection page did not contain the expected selector")
        self.bootstrapped = True

    def select_term(self, term_code: str) -> None:
        if not self.bootstrapped:
            self.bootstrap()
        result = self.get_json(
            "/term/search?mode=search",
            form={
                "term": term_code,
                "studyPath": "",
                "studyPathText": "",
                "startDatepicker": "",
                "endDatepicker": "",
            },
            referer=self.url(TERM_SELECTION_PATH),
        )
        expected = "/StudentRegistrationSsb/ssb/classSearch/classSearch"
        if not isinstance(result, dict) or result.get("fwdURL") != expected:
            raise BannerError(f"Banner did not accept exact term code {term_code!r}")
        body, content_type = self.request("/classSearch/classSearch")
        if content_type != "text/html" or b"searchResults" not in body:
            raise BannerError(f"Banner class-search bootstrap failed for term {term_code}")


def normalize_term(value: Any, discovered_at: str) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    code = str(value.get("code", "")).strip()
    description = str(value.get("description", "")).strip()
    if not code or not description:
        return None
    return {
        "code": code,
        "description": description,
        "discovered_at": discovered_at,
        "view_only": "view only" in description.casefold(),
    }


def discover_terms(client: BannerSession, page_size: int = 10, delay: float = 0.0) -> dict[str, Any]:
    if page_size < 1 or page_size > 500:
        raise ValueError("page_size must be between 1 and 500")
    client.bootstrap()
    discovered_at = utc_now()
    by_code: dict[str, dict[str, Any]] = {}
    offset = 1
    while True:
        page = client.get_json(
            TERM_ENDPOINT_PATH,
            query={"searchTerm": "", "offset": offset, "max": page_size},
            referer=client.url(TERM_SELECTION_PATH),
        )
        if not isinstance(page, list):
            raise BannerError("term selector returned a non-list response")
        new_codes = 0
        for raw_term in page:
            term = normalize_term(raw_term, discovered_at)
            if term is None:
                continue
            if term["code"] not in by_code:
                by_code[term["code"]] = term
                new_codes += 1
        if not page or new_codes == 0 or len(page) < page_size:
            break
        # Banner's getTerms endpoint treats offset as a 1-based page number,
        # not as a record offset (observed again 2026-08-31 with max=10).
        offset += 1
        if delay:
            time.sleep(delay)

    terms = sorted(by_code.values(), key=lambda row: row["code"], reverse=True)
    if not terms:
        raise BannerError("public term selector exposed no valid exact term codes")
    codes = [term["code"] for term in terms]
    return {
        "schema_version": SCHEMA_VERSION,
        "tool_version": TOOL_VERSION,
        "generated_at": discovered_at,
        "source_url": client.url(TERM_SELECTION_PATH),
        "source_endpoint": client.url(TERM_ENDPOINT_PATH),
        "term_count": len(terms),
        "coverage": {"earliest_term_code": min(codes), "latest_term_code": max(codes)},
        "terms": terms,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("resources/courses/public-terms.json"))
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help=argparse.SUPPRESS)
    parser.add_argument("--page-size", type=int, default=10)
    parser.add_argument("--delay", type=float, default=0.1, help="delay between selector pages")
    parser.add_argument("--timeout", type=float, default=30.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        artifact = discover_terms(BannerSession(args.base_url, args.timeout), args.page_size, args.delay)
        atomic_write_json(args.output, artifact)
    except (BannerError, OSError, ValueError) as exc:
        print(f"term discovery failed: {exc}", file=sys.stderr)
        return 1
    print(f"Discovered {artifact['term_count']} exact public terms -> {args.output}")
    print(
        f"Coverage: {artifact['coverage']['earliest_term_code']} through "
        f"{artifact['coverage']['latest_term_code']} (observed, not hard-coded)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
