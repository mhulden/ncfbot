#!/usr/bin/env python3
"""Shared public-only HTTP safety helpers for the source pipeline."""

from __future__ import annotations

import http.cookiejar
import ipaddress
import re
import socket
import urllib.parse
from collections.abc import Iterable

import requests


DEFAULT_AUTH_SIGNALS = (
    "login",
    "signin",
    "auth",
    "sso",
    "myncf",
    "canvas",
    "self-service",
    "secure",
    "portal",
    "myaccount",
)


class RejectAllCookies(http.cookiejar.DefaultCookiePolicy):
    """Cookie policy that refuses storage and transmission."""

    def set_ok(self, cookie, request):
        return False

    def return_ok(self, cookie, request):
        return False

    def domain_return_ok(self, domain, request):
        return False

    def path_return_ok(self, path, request):
        return False


def make_no_cookie_session(user_agent: str, accept: str) -> requests.Session:
    session = requests.Session()
    session.trust_env = False
    session.headers.update({"User-Agent": user_agent, "Accept": accept})
    cookie_jar = requests.cookies.RequestsCookieJar()
    cookie_jar.set_policy(RejectAllCookies())
    session.cookies = cookie_jar
    session.max_redirects = 5
    return session


def hostname(url: str) -> str:
    try:
        return (urllib.parse.urlsplit(url).hostname or "").lower().rstrip(".")
    except ValueError:
        return ""


def is_allowed_domain(url: str, allowed_domains: Iterable[str]) -> bool:
    host = hostname(url)
    domains = {domain.lower().rstrip(".") for domain in allowed_domains}
    return bool(host) and any(host == domain or host.endswith("." + domain) for domain in domains)


def looks_like_auth(url: str, auth_signals: Iterable[str] = DEFAULT_AUTH_SIGNALS) -> bool:
    parsed = urllib.parse.urlsplit(url)
    host = (parsed.hostname or "").lower()
    if "myncf" in host or "instructure.com" in host:
        return True
    tokens = {
        token
        for token in re.split(r"[^a-z0-9]+", f"{parsed.path} {parsed.fragment}".lower())
        if token
    }
    normalized_signals = {signal.lower() for signal in auth_signals}
    return bool(tokens & normalized_signals)


def private_target_error(url: str, *, resolve_dns: bool = False) -> str | None:
    host = hostname(url)
    if not host:
        return "URL has no valid hostname"
    if host == "localhost" or host.endswith(".localhost") or host.endswith(".local"):
        return "private/local network target"

    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None and not literal.is_global:
        return "private/local network target"

    if not resolve_dns:
        return None
    try:
        addresses = {
            result[4][0]
            for result in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        }
    except OSError as exc:
        return f"hostname resolution failed: {exc}"
    for address in addresses:
        try:
            parsed_address = ipaddress.ip_address(address)
        except ValueError:
            return f"hostname resolved to an invalid address: {address}"
        if not parsed_address.is_global:
            return f"hostname resolves to private/local address: {address}"
    return None


def validate_public_url(
    url: str,
    allowed_domains: Iterable[str],
    auth_signals: Iterable[str] = DEFAULT_AUTH_SIGNALS,
    *,
    resolve_dns: bool = False,
) -> str | None:
    try:
        parsed = urllib.parse.urlsplit(url)
        port = parsed.port
    except ValueError:
        return "malformed URL"
    if parsed.scheme.lower() != "https":
        return "not HTTPS"
    if parsed.username is not None or parsed.password is not None:
        return "embedded credentials are not allowed"
    if port not in {None, 443}:
        return f"nonstandard HTTPS port is not allowed: {port}"
    if not is_allowed_domain(url, allowed_domains):
        return f"domain not in allowlist: {parsed.hostname or ''}"
    private_error = private_target_error(url, resolve_dns=resolve_dns)
    if private_error:
        return private_error
    if looks_like_auth(url, auth_signals):
        return "auth signal detected in URL"
    return None
