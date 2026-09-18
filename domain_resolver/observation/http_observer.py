"""Safe HTTP/HTTPS observation.

Attempts HTTPS first (HTTP fallback only on transport-level failure), following
redirects manually so every hop is validated, recorded, bounded, and loop-safe.
All outputs are factual observations. HTTP status codes and failures are never
interpreted as relationship or liveness judgements — a 403/404/timeout/DNS
failure is recorded as an observation, nothing more.
"""

from __future__ import annotations

import hashlib
import ssl
import time

import httpx

from domain_resolver.models.entities import ObservationErrorCategory
from domain_resolver.observation.errors import (
    ObservationError,
    classify_http_exception,
    classify_status,
)
from domain_resolver.observation.html_extract import extract_html_summary
from domain_resolver.observation.limits import DEFAULT_LIMITS, ObservationLimits
from domain_resolver.observation.network import GuardedTransport, validate_target
from domain_resolver.observation.results import HtmlSummary, HttpObservation, RedirectHop

_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_CAPTURED_HEADERS = frozenset(
    {"content-type", "content-length", "location", "server", "x-robots-tag"}
)
_FALLBACK_CATEGORIES = frozenset(
    {
        ObservationErrorCategory.SSL_ERROR,
        ObservationErrorCategory.CONNECTION_ERROR,
        ObservationErrorCategory.TIMEOUT,
    }
)


class HttpObserver:
    """Observe a hostname over HTTP(S) with strict, bounded, safe behaviour."""

    def __init__(
        self,
        limits: ObservationLimits = DEFAULT_LIMITS,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._limits = limits
        # The default transport validates and pins every connection (SSRF-safe).
        self._transport = transport if transport is not None else GuardedTransport(limits)

    def observe(self, hostname: str) -> HttpObservation:
        started = time.monotonic()
        deadline = started + self._limits.total_timeout
        attempts: list[str] = []

        observation = self._observe_scheme("https", hostname, deadline, attempts)
        if observation.status_code is None and observation.error_category in _FALLBACK_CATEGORIES:
            fallback = self._observe_scheme("http", hostname, deadline, attempts)
            if fallback.status_code is not None or fallback.error_category is not None:
                observation = fallback

        observation.scheme_attempts = attempts
        observation.elapsed_ms = round((time.monotonic() - started) * 1000, 3)
        return observation

    def _observe_scheme(
        self, scheme: str, hostname: str, deadline: float, attempts: list[str]
    ) -> HttpObservation:
        attempts.append(scheme)
        requested = httpx.URL(f"{scheme}://{hostname}/")
        observation = HttpObservation(requested_url=str(requested))
        chain: list[RedirectHop] = []
        visited: set[str] = set()
        current = requested

        timeout = httpx.Timeout(
            connect=self._limits.connect_timeout,
            read=self._limits.read_timeout,
            write=self._limits.write_timeout,
            pool=self._limits.pool_timeout,
        )
        headers = {"User-Agent": self._limits.user_agent, "Accept": "text/html,*/*"}

        try:
            with httpx.Client(
                transport=self._transport,
                timeout=timeout,
                follow_redirects=False,
                headers=headers,
            ) as client:
                for request_index in range(self._limits.max_redirects + 1):
                    if time.monotonic() > deadline:
                        raise httpx.ReadTimeout("total observation timeout exceeded")
                    if str(current) in visited:
                        return self._finish_redirect_limit(
                            observation, chain, current, "redirect loop detected"
                        )
                    visited.add(str(current))
                    validate_target(current, self._limits)

                    with client.stream("GET", current) as response:
                        status = response.status_code
                        location = response.headers.get("location")
                        if status in _REDIRECT_STATUSES and location:
                            if request_index >= self._limits.max_redirects:
                                return self._finish_redirect_limit(
                                    observation, chain, current, "maximum redirects exceeded"
                                )
                            target = current.join(location)
                            validate_target(target, self._limits)
                            chain.append(
                                RedirectHop(
                                    source_url=str(current),
                                    status_code=status,
                                    location=location,
                                    target_url=str(target),
                                )
                            )
                            current = target
                            continue
                        self._finish_final(observation, response, chain, current)

                    # Follow a <meta http-equiv="refresh"> redirect declared in the
                    # page HTML, under the same redirect budget, loop detection, and
                    # SSRF validation as an HTTP redirect. No JavaScript is executed.
                    meta_target = self._meta_refresh_target(observation, current)
                    if (
                        meta_target is not None
                        and request_index < self._limits.max_redirects
                        and str(meta_target) not in visited
                    ):
                        refresh_url = (
                            observation.html.meta_refresh_url if observation.html else None
                        )
                        chain.append(
                            RedirectHop(
                                source_url=str(current),
                                status_code=observation.status_code or 200,
                                location=refresh_url or "",
                                target_url=str(meta_target),
                                kind="meta_refresh",
                            )
                        )
                        current = meta_target
                        continue
                    return observation

                # Defensive: the loop always returns above.
                return self._finish_redirect_limit(
                    observation, chain, current, "maximum redirects exceeded"
                )
        except (ObservationError, httpx.HTTPError, ssl.SSLError) as exc:
            category, detail = classify_http_exception(exc)
            observation.redirect_chain = chain
            observation.error_category = category
            observation.error_detail = detail
            if chain:
                observation.final_url = str(current)
                observation.final_hostname = current.host
            return observation

    def _finish_redirect_limit(
        self,
        observation: HttpObservation,
        chain: list[RedirectHop],
        current: httpx.URL,
        detail: str,
    ) -> HttpObservation:
        observation.redirect_chain = chain
        observation.error_category = ObservationErrorCategory.REDIRECT_LIMIT
        observation.error_detail = detail
        observation.final_url = str(current)
        observation.final_hostname = current.host
        return observation

    def _meta_refresh_target(
        self, observation: HttpObservation, current: httpx.URL
    ) -> httpx.URL | None:
        """Resolve a validated meta-refresh target, or None if absent/unsafe."""
        html = observation.html
        if html is None or not html.meta_refresh_url:
            return None
        try:
            target = current.join(html.meta_refresh_url)
            validate_target(target, self._limits)
        except (ObservationError, httpx.InvalidURL, ValueError):
            return None
        return target

    def _finish_final(
        self,
        observation: HttpObservation,
        response: httpx.Response,
        chain: list[RedirectHop],
        current: httpx.URL,
    ) -> HttpObservation:
        body, too_large = self._read_capped(response)
        observation.status_code = response.status_code
        observation.http_version = response.http_version
        observation.headers = {
            key.lower(): value
            for key, value in response.headers.items()
            if key.lower() in _CAPTURED_HEADERS
        }
        observation.content_type = response.headers.get("content-type")
        observation.redirect_chain = chain
        observation.final_url = str(current)
        observation.final_hostname = current.host
        observation.response_size_bytes = len(body)

        if too_large:
            observation.error_category = ObservationErrorCategory.RESPONSE_TOO_LARGE
            observation.error_detail = "response exceeded maximum body size"
            return observation

        observation.error_category = classify_status(response.status_code)

        if self._is_html(observation.content_type):
            content_hash = hashlib.sha256(body).hexdigest()
            try:
                text = body.decode(self._charset(observation.content_type), errors="replace")
                observation.html = extract_html_summary(text, content_hash, self._limits)
            except Exception as exc:  # noqa: BLE001 - parser failure is recorded, not raised
                observation.html = HtmlSummary(content_hash=content_hash)
                if observation.error_category is None:
                    observation.error_category = ObservationErrorCategory.PARSER_ERROR
                    observation.error_detail = f"parser error: {type(exc).__name__}"
        return observation

    def _read_capped(self, response: httpx.Response) -> tuple[bytes, bool]:
        chunks: list[bytes] = []
        total = 0
        too_large = False
        for chunk in response.iter_bytes():
            chunks.append(chunk)
            total += len(chunk)
            if total > self._limits.max_body_bytes:
                too_large = True
                break
        return b"".join(chunks)[: self._limits.max_body_bytes], too_large

    @staticmethod
    def _is_html(content_type: str | None) -> bool:
        if not content_type:
            return False
        base = content_type.split(";", 1)[0].strip().lower()
        return base in {"text/html", "application/xhtml+xml"}

    @staticmethod
    def _charset(content_type: str | None) -> str:
        if content_type and "charset=" in content_type:
            return content_type.split("charset=", 1)[1].split(";", 1)[0].strip() or "utf-8"
        return "utf-8"
