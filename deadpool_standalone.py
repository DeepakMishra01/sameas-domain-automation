#!/usr/bin/env python3
"""Standalone, single-file runner for the evidence-escalation deadpool flow.

This consolidates the second flow (DEAD / ALIVE / ACQUIRED_MERGED / REVIEW),
not the separate database-backed six-condition/gray-zone evaluator.

Dependencies: httpx, dnspython, openpyxl. Playwright is optional.

Example:
  python deadpool_standalone.py domains.xlsx --out results.xlsx --no-llm
  python deadpool_standalone.py domains.csv --out results.xlsx --mca mca.csv

Optional environment:
  DERE_SERPER_API_KEY, DERE_LLM_PROVIDER (ollama|gemini|openai|nvidia),
  DERE_LLM_MODEL, DERE_LLM_API_KEY, DERE_GEMINI_API_KEY, DERE_NVIDIA_API_KEY,
  DERE_LLM_BASE_URL, DERE_OLLAMA_URL.
  Values can also be loaded from a local .env file; existing environment values
  take precedence. Never commit API keys or private registry files to GitHub.

This script only writes a results workbook. It never changes company status.
Network failures are inconclusive; they are not treated as proof of shutdown.
"""

from __future__ import annotations

import argparse
import csv
from html.parser import HTMLParser
import ipaddress
import json
import os
import re
import socket
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import dns.exception
import dns.resolver
import httpx
import openpyxl
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter


# ------------------------------- Data contracts ----------------------------

class Status(StrEnum):
    DEAD = "DEAD"
    ALIVE = "ALIVE"
    ACQUIRED_MERGED = "ACQUIRED_MERGED"
    REVIEW = "REVIEW"
    ERROR = "ERROR"


class SiteState(StrEnum):
    OPERATIONAL = "OPERATIONAL"
    NOT_WORKING = "NOT_WORKING"
    INCONCLUSIVE = "INCONCLUSIVE"


class DnsState(StrEnum):
    RESOLVED = "RESOLVED"
    NXDOMAIN = "NXDOMAIN"
    PARKED_NS = "PARKED_NS"
    TRANSIENT = "TRANSIENT"


@dataclass
class SiteEvidence:
    state: SiteState
    dns_state: DnsState
    status_code: int | None = None
    text: str = ""
    detail: str = ""
    conclusive_death: bool = False


@dataclass
class Verdict:
    domain: str
    status: Status
    confidence: float
    deadpool_year: int | None = None
    founded_year: int | None = None
    tier: str = "tier1"
    sources: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    llm_status: str = ""


# ------------------------------- DNS + HTTP --------------------------------

PARKING_NS = (
    "sedoparking.com", "sedo.com", "bodis.com", "parkingcrew.net", "parkingcrew.com",
    "cashparking.com", "afternic.com", "dan.com", "above.com", "parklogic.com",
    "undeveloped.com", "hugedomains.com", "voodoo.com", "fabulous.com", "parked.com",
)
PARKED_TEXT = (
    "domain for sale", "buy this domain", "parked domain", "this domain is parked",
    "domain parking", "account suspended", "site suspended", "website suspended",
    "under construction", "coming soon", "site not found", "page not found",
    "default web page", "welcome to nginx", "apache2 ubuntu default page",
    "this domain has been registered", "future home of something quite cool",
)
SHUTDOWN_TEXT = (
    "we have shut down", "we've shut down", "has shut down", "ceased operations",
    "ceased trading", "no longer operating", "no longer in business", "closing down",
    "permanently closed", "service discontinued", "winding down", "out of business",
)
ALIVE_TEXT_MIN = 200
UA = "DeadpoolEvidenceRunner/1.0 (contact: operator)"


def _dns_state(host: str) -> DnsState:
    resolver = dns.resolver.Resolver()
    resolver.timeout = 3.0
    resolver.lifetime = 6.0
    ns_values: list[str] = []
    address_found = False
    for kind in ("NS", "A", "AAAA"):
        try:
            ans = resolver.resolve(host, kind, raise_on_no_answer=False)
            vals = [r.to_text().lower().rstrip(".") for r in ans]
            if kind == "NS":
                ns_values.extend(vals)
            elif vals:
                address_found = True
        except dns.resolver.NXDOMAIN:
            return DnsState.NXDOMAIN
        except (dns.exception.Timeout, dns.resolver.NoNameservers):
            continue
        except dns.exception.DNSException:
            continue
    if any(marker in " ".join(ns_values) for marker in PARKING_NS):
        return DnsState.PARKED_NS
    if address_found:
        return DnsState.RESOLVED
    if ns_values:
        return DnsState.TRANSIENT
    return DnsState.TRANSIENT


class _VisibleText(HTMLParser):
    """Extract visible-ish page text while discarding script/style markup."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._hidden_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"script", "style", "noscript", "svg"}:
            self._hidden_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "noscript", "svg"} and self._hidden_depth:
            self._hidden_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._hidden_depth:
            value = data.strip()
            if value:
                self.parts.append(value)


def _visible_text(html: str) -> str:
    parser = _VisibleText()
    try:
        parser.feed(html)
        return re.sub(r"\s+", " ", " ".join(parser.parts)).strip()
    except Exception:
        return ""


def _public_target(url: str) -> bool:
    """Reject non-public IPs/hosts and unsafe redirect destinations."""
    try:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return False
        host = parsed.hostname
        try:
            addresses = [ipaddress.ip_address(host)]
        except ValueError:
            addresses = [ipaddress.ip_address(x[4][0]) for x in socket.getaddrinfo(host, None)]
        return bool(addresses) and all(ip.is_global for ip in addresses)
    except (OSError, ValueError):
        return False


def _fetch_site(host: str, dns_state: DnsState) -> SiteEvidence:
    if dns_state is DnsState.NXDOMAIN:
        return SiteEvidence(SiteState.NOT_WORKING, dns_state, detail="DNS NXDOMAIN", conclusive_death=True)
    if dns_state is DnsState.PARKED_NS:
        return SiteEvidence(SiteState.NOT_WORKING, dns_state, detail="parking nameserver", conclusive_death=True)

    last_detail = "no successful HTTP response"
    for scheme in ("https", "http"):
        url = f"{scheme}://{host}/"
        if not _public_target(url):
            last_detail = "host did not resolve to a public IP (or DNS lookup failed)"
            continue
        try:
            with httpx.Client(timeout=httpx.Timeout(12.0), follow_redirects=False,
                              headers={"User-Agent": UA}) as client:
                for _ in range(6):
                    if not _public_target(url):
                        return SiteEvidence(SiteState.INCONCLUSIVE, dns_state, detail="unsafe or non-public redirect target")
                    response = client.get(url)
                    if response.status_code in {301, 302, 303, 307, 308}:
                        location = response.headers.get("location")
                        if not location:
                            break
                        url = urljoin(url, location)
                        continue
                    code = response.status_code
                    text = _visible_text(response.text[:500_000])
                    low = text.lower()
                    if code in {404, 410, 451}:
                        return SiteEvidence(SiteState.NOT_WORKING, dns_state, code, text,
                                            f"confirmed HTTP {code}", True)
                    if code in {403, 429} or code >= 500:
                        return SiteEvidence(SiteState.INCONCLUSIVE, dns_state, code, text,
                                            f"transient/access HTTP {code}")
                    if 200 <= code < 300:
                        if any(pattern in low for pattern in PARKED_TEXT):
                            return SiteEvidence(SiteState.NOT_WORKING, dns_state, code, text,
                                                "parked/error page pattern", False)
                        return SiteEvidence(SiteState.OPERATIONAL, dns_state, code, text,
                                            "operational HTTP response")
                    return SiteEvidence(SiteState.INCONCLUSIVE, dns_state, code, text,
                                        f"ambiguous HTTP {code}")
                last_detail = "redirect limit reached"
        except httpx.HTTPError as exc:
            last_detail = f"HTTP transport error: {type(exc).__name__}"
    return SiteEvidence(SiteState.INCONCLUSIVE, dns_state, detail=last_detail)


# -------------------------------- RDAP --------------------------------------

DEAD_RDAP = ("redemption period", "pending delete", "redemptionperiod", "pendingdelete",
             "client hold", "server hold", "clienthold", "serverhold", "inactive")
TWO_LEVEL_SUFFIXES = {"co.in", "net.in", "org.in", "ac.in", "gov.in", "edu.in", "co.uk",
                      "org.uk", "com.sg", "com.au", "net.au", "org.au", "com.br", "co.jp"}


def _registrable_domain(host: str) -> str:
    labels = host.lower().strip(".").split(".")
    if len(labels) <= 2:
        return ".".join(labels)
    suffix2 = ".".join(labels[-2:])
    return ".".join(labels[-3:]) if suffix2 in TWO_LEVEL_SUFFIXES else suffix2


def _rdap(host: str) -> tuple[bool, str]:
    try:
        r = httpx.get("https://rdap.org/domain/" + _registrable_domain(host),
                      timeout=12, follow_redirects=True, headers={"User-Agent": UA})
        if r.status_code == 404:
            return True, "RDAP says domain not registered (404)"
        if r.status_code >= 400:
            return False, f"RDAP lookup unavailable ({r.status_code})"
        data = r.json()
        statuses = [str(s).lower() for s in data.get("status", [])]
        expired = False
        for event in data.get("events", []):
            if str(event.get("eventAction", "")).lower() == "expiration":
                try:
                    expiry = datetime.fromisoformat(str(event["eventDate"]).replace("Z", "+00:00"))
                    expired = expiry < datetime.now(UTC)
                except (KeyError, ValueError):
                    pass
        dead = expired or any(any(term in s for term in DEAD_RDAP) for s in statuses)
        return dead, "RDAP registration lapsed/held" if dead else "RDAP registered"
    except (httpx.HTTPError, ValueError, KeyError):
        return False, "RDAP lookup unavailable"


# --------------------------- Wayback evidence ------------------------------

def _wayback(host: str) -> tuple[int | None, str]:
    params = {"url": host, "output": "json", "fl": "timestamp,original,statuscode",
              "filter": "statuscode:200", "limit": "-5"}
    try:
        r = httpx.get("https://web.archive.org/cdx/search/cdx", params=params, timeout=12,
                      headers={"User-Agent": UA})
        r.raise_for_status()
        data = r.json()
        years = [int(str(row[0])[:4]) for row in data[1:] if len(row) >= 3
                 and str(row[2]) == "200" and str(row[0])[:4].isdigit()]
        y = max(years) if years else None
        return y, f"Wayback latest working snapshot year={y}" if y else "Wayback has no 200 snapshot"
    except (httpx.HTTPError, ValueError, IndexError, TypeError):
        return None, "Wayback lookup unavailable"


# -------------------------- Registry file support --------------------------

def _load_records(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() in {".xlsx", ".xlsm"}:
        ws = openpyxl.load_workbook(path, read_only=True, data_only=True).worksheets[0]
        rows = ws.iter_rows(values_only=True)
        headers = [str(x or "") for x in next(rows, ())]
        return [dict(zip(headers, row)) for row in rows]
    with path.open(newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def _registry_status(company_id: str, name: str, paths: list[Path]) -> tuple[str, int | None, str] | None:
    if not paths:
        return None
    norm = lambda s: re.sub(r"[^a-z0-9]", "", str(s or "").lower())
    key_id, key_name = norm(company_id), norm(name)
    for path in paths:
        try:
            records = _load_records(path)
        except Exception:
            continue
        for row in records:
            vals = {str(k).lower(): v for k, v in row.items()}
            rid = next((v for k, v in vals.items() if "cin" in k or "llpin" in k), "")
            rname = next((v for k, v in vals.items() if "name" in k), "")
            raw_status = next((v for k, v in vals.items() if "status" in k), "")
            if not ((key_id and norm(rid) == key_id) or (key_name and norm(rname) == key_name)):
                continue
            low = str(raw_status).lower()
            year_match = re.search(r"(?:19|20)\d{2}", str(row))
            year = int(year_match.group()) if year_match else None
            if any(w in low for w in ("strike off", "struck off", "dissolved", "liquidated")):
                return "DEAD", year, f"registry status: {raw_status}"
            if any(w in low for w in ("amalgamat", "merged")):
                return "ACQUIRED_MERGED", year, f"registry status: {raw_status}"
            if "liquidation" in low:
                return "REVIEW", year, f"registry status: {raw_status}"
    return None


# ----------------------------- Search + LLM -------------------------------

def _serper_search(name: str, host: str) -> tuple[bool, str]:
    key = os.getenv("DERE_SERPER_API_KEY", "")
    if not key:
        return False, ""
    query = f'{name or host} {host} company shut down OR closed OR "ceased operations" OR acquired OR bankruptcy'
    try:
        r = httpx.post("https://google.serper.dev/search", headers={"X-API-KEY": key,
                        "Content-Type": "application/json"}, json={"q": query, "num": 8}, timeout=30)
        r.raise_for_status()
        data = r.json()
        chunks = []
        kg = data.get("knowledgeGraph")
        if isinstance(kg, dict):
            chunks.append("knowledge_graph: " + json.dumps(kg, ensure_ascii=False))
        for item in data.get("organic", [])[:8]:
            if isinstance(item, dict):
                chunks.append(f"- {item.get('title','')}: {item.get('snippet','')}")
        return True, "\n".join(chunks)
    except Exception:
        return True, ""


LLM_SYSTEM = """You classify whether a company has stopped operating, using ONLY supplied evidence.
Return JSON: {"status":"DEAD|ALIVE|ACQUIRED|UNCERTAIN","deadpool_year":null,
"founded_year":null,"confidence":0.0,"reasoning":"...","evidence_quote":"..."}.
Transient errors and historical Wayback snapshots alone are not proof of death or life.
Acquired/merged means the business continues under a parent and is NOT deadpooled.
If evidence is thin or conflicting, answer UNCERTAIN. ALIVE requires current live real content."""


def _llm(system: str, prompt: str) -> tuple[str, str] | None:
    provider = os.getenv("DERE_LLM_PROVIDER", "ollama").lower()
    model = os.getenv("DERE_LLM_MODEL", "qwen2.5:14b-instruct")
    try:
        if provider == "ollama":
            base = os.getenv("DERE_OLLAMA_URL", "http://localhost:11434").rstrip("/")
            r = httpx.post(base + "/api/chat", json={"model": model, "messages": [
                {"role": "system", "content": system}, {"role": "user", "content": prompt}],
                "stream": False, "format": "json", "options": {"temperature": 0}}, timeout=120)
            r.raise_for_status()
            return r.json()["message"]["content"], model
        if provider == "gemini":
            key = os.getenv("DERE_GEMINI_API_KEY", "")
            model = os.getenv("DERE_LLM_MODEL", "gemini-1.5-flash")
            if not key: return None
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
            r = httpx.post(url, json={"system_instruction": {"parts": [{"text": system}]},
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0, "responseMimeType": "application/json"}}, timeout=60)
            r.raise_for_status()
            return r.json()["candidates"][0]["content"]["parts"][0]["text"], model
        if provider in {"openai", "nvidia"}:
            key = os.getenv("DERE_LLM_API_KEY", "") if provider == "openai" else os.getenv("DERE_NVIDIA_API_KEY", os.getenv("DERE_LLM_API_KEY", ""))
            base_default = "https://api.openai.com/v1" if provider == "openai" else "https://integrate.api.nvidia.com/v1"
            base = os.getenv("DERE_LLM_BASE_URL", base_default).rstrip("/")
            model = os.getenv("DERE_LLM_MODEL", "gpt-4o-mini" if provider == "openai" else "meta/llama-3.3-70b-instruct")
            if not key: return None
            r = httpx.post(base + "/chat/completions", headers={"Authorization": f"Bearer {key}"},
                json={"model": model, "messages": [{"role": "system", "content": system},
                    {"role": "user", "content": prompt}], "temperature": 0}, timeout=90)
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"], model
    except Exception:
        return None
    return None


# ------------------------------- Decision ----------------------------------

def _guard_year(year: int | None, founded: int | None) -> int | None:
    return None if year and founded and year < founded else year


def determine(host: str, *, name: str = "", company_id: str = "", founded: int | None = None,
              registry_files: list[Path] | None = None, use_archive: bool = True,
              use_llm: bool = True, is_funded: bool | None = None) -> Verdict:
    sources: list[str] = []
    reasons: list[str] = []
    reg = _registry_status(company_id, name, registry_files or [])
    if reg:
        status, year, reason = reg
        return Verdict(host, Status(status), 0.99, year, founded, "registry", ["registry"], [reason])

    dns_state = _dns_state(host)
    site = _fetch_site(host, dns_state)
    sources.append(f"http:{site.state.value}")
    if site.state is SiteState.OPERATIONAL and len(site.text) >= ALIVE_TEXT_MIN:
        return Verdict(host, Status.ALIVE, 0.90, founded_year=founded, tier="tier1",
                       sources=sources, reasons=["operational website with real content"])

    rdap_dead, rdap_reason = _rdap(host)
    if rdap_dead:
        sources.append("rdap:dead")
    year, archive_reason = _wayback(host) if use_archive else (None, "Wayback skipped")
    if use_archive:
        sources.append(f"archive:last200={year}")
    year = _guard_year(year, founded)
    if site.conclusive_death:
        return Verdict(host, Status.DEAD, 0.95, year, founded, "tier1", sources,
                       [f"website conclusive: {site.detail}"])
    if rdap_dead:
        return Verdict(host, Status.DEAD, 0.95, year, founded, "tier1", sources, [rdap_reason])

    render_text = ""
    render_title = ""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_default_timeout(15_000)
            try:
                page.goto(f"https://{host}/", wait_until="domcontentloaded")
            except Exception:
                page.goto(f"http://{host}/", wait_until="domcontentloaded")
            render_title = page.title()
            render_text = page.locator("body").inner_text() if page.locator("body").count() else ""
            browser.close()
        sources.append("render")
        rendered_low = (render_title + " " + render_text).lower()
        banner = next((p for p in SHUTDOWN_TEXT if p in rendered_low), None)
        if banner:
            return Verdict(host, Status.DEAD, 0.88, year, founded, "render", sources,
                           [f"rendered shutdown text: {banner}"])
        if len(render_text.strip()) >= ALIVE_TEXT_MIN and not site.conclusive_death:
            return Verdict(host, Status.ALIVE, 0.88, founded_year=founded, tier="render",
                           sources=sources, reasons=["rendered real content"])
    except Exception:
        pass

    if use_llm:
        queried, search = _serper_search(name, host)
        if queried:
            sources.append(f"search:{'results' if search else 'empty'}")
        bundle = [f"domain: {host}", f"company: {name}",
                  f"website: {site.state.value}; HTTP {site.status_code}; DNS {site.dns_state.value}; {site.detail}",
                  f"RDAP: {rdap_reason}", f"archive: {archive_reason}; year={year}"]
        if is_funded is not None:
            bundle.append(f"funding: {'funded' if is_funded else 'unfunded'}")
        if render_text:
            bundle.append("rendered text: " + render_text[:1500])
        if search:
            bundle.append("search results:\n" + search[:2500])
        result = _llm(LLM_SYSTEM, f"COMPANY: {name or host}\nDOMAIN: {host}\n\nEVIDENCE:\n" + "\n".join(bundle))
        if result:
            try:
                raw, model = result
                obj = json.loads(raw[raw.find("{"):raw.rfind("}") + 1])
                s = str(obj.get("status", "UNCERTAIN")).upper()
                conf = max(0.0, min(1.0, float(obj.get("confidence", 0))))
                yrs = obj.get("deadpool_year")
                fy = founded or obj.get("founded_year")
                try: yrs = int(yrs) if yrs else None
                except (TypeError, ValueError): yrs = None
                try: fy = int(fy) if fy else None
                except (TypeError, ValueError): fy = None
                yrs = _guard_year(yrs or year, fy)
                sources.append(f"llm:{s}:{conf:.2f}:{model}")
                reasons.append(str(obj.get("reasoning") or obj.get("evidence_quote") or "LLM verdict"))
                if conf >= 0.80 and s == "DEAD":
                    return Verdict(host, Status.DEAD, conf, yrs, fy, "search_llm", sources, reasons, s)
                if conf >= 0.80 and s == "ALIVE":
                    return Verdict(host, Status.ALIVE, conf, None, fy, "search_llm", sources, reasons, s)
                if conf >= 0.80 and s == "ACQUIRED":
                    return Verdict(host, Status.ACQUIRED_MERGED, conf, None, fy, "search_llm", sources, reasons, s)
                return Verdict(host, Status.REVIEW, conf, yrs if s == "DEAD" else None,
                               fy, "search_llm", sources, reasons, s)
            except (ValueError, TypeError, KeyError):
                pass
    reasons.append("no high-confidence signal; needs manual review")
    return Verdict(host, Status.REVIEW, 0.0, year, founded,
                   "render" if render_text else "tier1", sources, reasons)


# ----------------------------------- CLI ------------------------------------

def _first(row: dict[str, Any], *names: str) -> str:
    for key, val in row.items():
        if str(key).strip().lower() in names and val not in (None, ""):
            return str(val).strip()
    return ""


def _read_input(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() in {".xlsx", ".xlsm"}:
        ws = openpyxl.load_workbook(path, read_only=True, data_only=True).worksheets[0]
        it = ws.iter_rows(values_only=True)
        headers = [str(v or "") for v in next(it, ())]
        return [dict(zip(headers, row)) for row in it if row and row[0]]
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def _year(raw: str) -> int | None:
    try:
        n = int(float(raw))
        return n if 1900 <= n <= 2100 else None
    except (TypeError, ValueError):
        return None


def _run_one(row: dict[str, Any], registries: list[Path], archive: bool, llm: bool) -> dict[str, Any]:
    host = _first(row, "domain", "domain_name", "domainname").lower().strip()
    name = _first(row, "name", "company_name", "companyname")
    company_id = _first(row, "external_company_id", "cin", "company_id")
    founded = _year(_first(row, "founded_year", "foundedyear", "founding_year"))
    stage = _first(row, "stage").lower()
    is_funded = stage not in ("", "unfunded") if stage else None
    try:
        d = determine(host, name=name, company_id=company_id, founded=founded,
                      registry_files=registries, use_archive=archive, use_llm=llm,
                      is_funded=is_funded)
        return {"domain": host, "name": name, "status": d.status.value,
                "confidence": d.confidence, "deadpool_year": d.deadpool_year,
                "founded_year": d.founded_year, "tier_reached": d.tier,
                "evidence_sources": "; ".join(d.sources), "reason": "; ".join(d.reasons)}
    except Exception as exc:
        return {"domain": host, "name": name, "status": "ERROR", "confidence": 0.0,
                "deadpool_year": None, "founded_year": founded, "tier_reached": "",
                "evidence_sources": "", "reason": f"{type(exc).__name__}: {exc}"}


def _write_xlsx(path: Path, rows: list[dict[str, Any]]) -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Deadpool determination"
    cols = ["domain", "name", "status", "confidence", "deadpool_year", "founded_year",
            "tier_reached", "evidence_sources", "reason"]
    ws.append(cols)
    for c in range(1, len(cols) + 1):
        ws.cell(1, c).font = Font(bold=True, color="FFFFFF")
        ws.cell(1, c).fill = PatternFill("solid", fgColor="1F2937")
    fills = {"DEAD": "C6EFCE", "ACQUIRED_MERGED": "BDD7EE", "REVIEW": "FFEB9C",
             "ALIVE": "F2F2F2", "ERROR": "FFC7CE"}
    for row in rows:
        ws.append([row.get(c) for c in cols])
        ws.cell(ws.max_row, 3).fill = PatternFill("solid", fgColor=fills.get(row["status"], "FFFFFF"))
        ws.cell(ws.max_row, 9).alignment = openpyxl.styles.Alignment(wrap_text=True, vertical="top")
    for i, width in enumerate([26, 24, 18, 12, 15, 15, 16, 52, 72], 1):
        ws.column_dimensions[get_column_letter(i)].width = width
    ws.freeze_panes = "A2"
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Single-file evidence-based deadpool determiner")
    parser.add_argument("input", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--no-archive", action="store_true")
    parser.add_argument("--no-llm", action="store_true")
    parser.add_argument("--mca", action="append", type=Path, default=[])
    parser.add_argument("--ibbi", action="append", type=Path, default=[])
    args = parser.parse_args()
    _load_dotenv(Path(".env"))
    rows = _read_input(args.input)[args.start:]
    if args.limit is not None:
        rows = rows[:args.limit]
    unique, seen = [], set()
    for row in rows:
        host = _first(row, "domain", "domain_name", "domainname").lower()
        if host and host not in seen:
            unique.append(row)
            seen.add(host)
    registries = args.mca + args.ibbi
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        results = list(pool.map(lambda r: _run_one(r, registries, not args.no_archive,
                                                   not args.no_llm), unique))
    _write_xlsx(args.out, results)
    from collections import Counter
    print(f"processed {len(results)} unique domains")
    print("statuses:", dict(Counter(r["status"] for r in results)))
    print("wrote:", args.out)
    return 0


def _load_dotenv(path: Path) -> None:
    """Load simple KEY=VALUE lines without replacing already-set environment."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


if __name__ == "__main__":
    raise SystemExit(main())
