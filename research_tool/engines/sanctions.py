"""Sanctions / restricted-entity screening engine.

Screens a person or organization name against the major public sanctions
lists and reports any match, which is central to cross-border due diligence
on restricted jurisdictions (e.g. the DPRK, Iran, Russia, Syria):

  * **OFAC SDN** (US Treasury) - ``sdn.csv``
  * **UN Security Council** consolidated list - ``consolidated.xml``
  * **EU** financial sanctions list - ``fullSanctionsList`` XML
  * **UK OFSI** consolidated list - CSV

The lists are downloaded once, parsed into a normalised
``{name, list, program, id, type}`` form and cached (respecting the cache
TTL) so repeated lookups are cheap. Matching is name-based (exact,
substring, token-set and edit-distance) and transliterates non-Latin
targets to Latin first. A match is a *lead*, not proof of identity, and is
labelled accordingly.
"""

from __future__ import annotations

import csv
import difflib
import io
import json
import re
from typing import Any
from urllib.parse import urlencode
from defusedxml import DefusedXmlException
from defusedxml import ElementTree as _SafeElementTree
from xml.etree import ElementTree

from ..logger import logger
from ..models.report import Finding
from ..utils.i18n import normalize_text, romanize
from .base import BaseEngine

# kind -> (label, download URL, parser). The label matches the ``list`` value
# each parser writes onto its entries, so filtering by source is unambiguous.
SANCTIONS_SOURCES: dict[str, tuple[str, str, str]] = {
    "ofac": ("OFAC SDN", "https://www.treasury.gov/ofac/downloads/sdn.csv", "ofac"),
    "un": ("UN", "https://scsanctions.un.org/resources/xml/en/consolidated.xml", "un"),
    "eu": ("EU",
           "https://webgate.ec.europa.eu/fsd/fsf/public/files/xmlFullSanctionsList/"
           "content?token=dG9rZW4tMjAxNw", "eu"),
    "uk": ("UK OFSI",
           "https://assets.publishing.service.gov.uk/media/"
           "consolidated_list_of_targets.csv", "uk"),
}

# Default similarity threshold for reporting a match.
DEFAULT_THRESHOLD = 0.8


def _clean(value: str | None) -> str:
    return normalize_text(value or "")


# Sanctions lists are downloaded from public endpoints (and may pass through a
# proxy/Tor). Refuse XML that declares a DTD/entities: those are the vector for
# "billion laughs" / external-entity expansion attacks against ElementTree.
_MAX_XML_CHARS = 80 * 1024 * 1024
# Scan the whole document: truncating to a fixed head window lets an attacker
# pad the payload with comments/whitespace so the DOCTYPE/ENTITY declaration
# lands outside the inspected slice.
_XML_DTD_RE = re.compile(r"<!\s*(?:doctype|entity)", re.IGNORECASE)


def _safe_xml_fromstring(text: str) -> ElementTree.Element | None:
    """Parse *text* only when it is a size-bounded, DTD-free XML document."""
    if len(text) > _MAX_XML_CHARS:
        logger.warning("[sanctions] XML payload exceeds size limit; skipped")
        return None
    if _XML_DTD_RE.search(text):
        logger.warning("[sanctions] XML with DOCTYPE/ENTITY rejected")
        return None
    try:
        return _SafeElementTree.fromstring(text)
    except (ElementTree.ParseError, DefusedXmlException):
        return None


# --------------------------------------------------------------------------
# Parsers - each takes raw text and returns a list of normalised entries.
# --------------------------------------------------------------------------
def parse_ofac(text: str) -> list[dict[str, Any]]:
    """Parse the OFAC SDN CSV (semi-broken quoting handled defensively)."""
    entries: list[dict[str, Any]] = []
    reader = csv.reader(io.StringIO(text))
    for row in reader:
        if len(row) < 4:
            continue
        ent_num, name, sdn_type, program = row[0], row[1], row[2], row[3]
        name = _clean(name)
        if not name or name.upper().replace(" ", "_").startswith("SDN_NAME"):
            continue
        entries.append({
            "name": name, "list": "OFAC SDN",
            "program": _clean(program), "id": _clean(ent_num),
            "type": _clean(sdn_type),
        })
    return entries


def parse_un(text: str) -> list[dict[str, Any]]:
    """Parse the UN consolidated list XML (individuals + entities + aliases)."""
    entries: list[dict[str, Any]] = []
    root = _safe_xml_fromstring(text)
    if root is None:
        return entries

    def _tag(el: ElementTree.Element) -> str:
        return el.tag.split("}")[-1].upper()

    for el in root.iter():
        tag = _tag(el)
        if tag not in ("INDIVIDUAL", "ENTITY"):
            continue
        parts = [child.text.strip() for child in el
                 if _tag(child) in ("FIRST_NAME", "SECOND_NAME", "THIRD_NAME",
                                    "FOURTH_NAME") and child.text]
        name = " ".join(parts).strip()
        if name:
            entries.append({
                "name": name, "list": "UN", "program": "",
                "id": el.get("DATAID") or el.get("dataid") or "",
                "type": tag.title(),
            })
        # Aliases (INDIVIDUAL_ALIAS / ENTITY_ALIAS -> ALIAS_NAME).
        for alias in el.iter():
            if _tag(alias) == "ALIAS_NAME" and alias.text:
                entries.append({
                    "name": alias.text.strip(), "list": "UN", "program": "",
                    "id": el.get("DATAID") or "", "type": "Alias",
                })
    return entries


def parse_eu(text: str) -> list[dict[str, Any]]:
    """Parse the EU financial-sanctions XML (``sanctionEntity``/``nameAlias``)."""
    entries: list[dict[str, Any]] = []
    root = _safe_xml_fromstring(text)
    if root is None:
        return entries
    for el in root.iter():
        if el.tag.split("}")[-1] != "sanctionEntity":
            continue
        subject = el.get("logicalId") or el.get("designationDetails") or ""
        for child in el:
            if child.tag.split("}")[-1] != "nameAlias":
                continue
            whole = child.get("wholeName")
            if whole:
                entries.append({
                    "name": whole.strip(), "list": "EU", "program": "",
                    "id": subject, "type": "Entity",
                })
    return entries


def parse_uk(text: str) -> list[dict[str, Any]]:
    """Parse the UK OFSI consolidated-list CSV (name columns 1..6)."""
    entries: list[dict[str, Any]] = []
    reader = csv.DictReader(io.StringIO(text))
    for row in reader:
        names = [v for k, v in row.items()
                 if k and k.lower().startswith("name") and v and v.strip()]
        name = _clean(" ".join(n.strip() for n in names))
        if not name:
            continue
        entries.append({
            "name": name, "list": "UK OFSI",
            "program": _clean(row.get("Regime") or row.get("regime") or ""),
            "id": _clean(row.get("Unique ID") or row.get("unique id") or ""),
            "type": _clean(row.get("Group Type") or row.get("group type") or ""),
        })
    return entries


_PARSERS = {"ofac": parse_ofac, "un": parse_un, "eu": parse_eu, "uk": parse_uk}


def parse_source(kind: str, text: str) -> list[dict[str, Any]]:
    """Dispatch to the right parser for *kind* (``ofac``/``un``/``eu``/``uk``)."""
    parser = _PARSERS.get(kind)
    if parser is None:
        return []
    try:
        return parser(text)
    except Exception as exc:  # noqa: BLE001 - malformed list must not crash
        logger.warning("[sanctions] failed to parse {} list: {}", kind, exc)
        return []


_CACHE_KEY = "sanctions entries v1"
# OpenSanctions aggregated API: 100+ lists (OFAC, UN, EU, UK + others) and
# PEPs in one endpoint - the richest single source for DPRK/Russia/Iran
# coverage. The API needs a (free) key; the bulk datasets below do not.
_OPEN_SANCTIONS_URL = "https://api.opensanctions.org/search/default"

# Key-free bulk datasets (FollowTheMoney JSON, one entity per line). Only the
# main sanctions lists are pulled to keep the download bounded.
_OPEN_SANCTIONS_BULK = (
    "https://data.opensanctions.org/datasets/latest/{dataset}/entities.ftm.json"
)
_BULK_DATASETS = ("us_ofac_sdn", "un_sc_sanctions", "eu_fsf", "gb_hmt_sanctions")
_OS_BULK_CACHE_KEY = "opensanctions bulk v1"


def parse_opensanctions_bulk(text: str) -> list[dict[str, Any]]:
    """Parse OpenSanctions FollowTheMoney JSON lines into normalised entries.

    Each line is one entity; ``properties.name`` and ``properties.alias``
    become candidate names. Malformed lines are skipped.
    """
    entries: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        props = obj.get("properties") or {}
        names = list(props.get("name") or []) + list(props.get("alias") or [])
        schema = obj.get("schema") or ""
        ent_id = obj.get("id") or ""
        for name in names:
            if isinstance(name, str) and name.strip():
                entries.append({
                    "name": name.strip(), "list": "OpenSanctions",
                    "program": "", "id": ent_id, "type": schema,
                })
    return entries


class SanctionsEngine(BaseEngine):
    """Screen a name against OFAC / UN / EU / UK sanctions lists."""

    name = "sanctions"
    category = "sanctions"

    # ------------------------------------------------------------------
    # Data acquisition
    # ------------------------------------------------------------------
    def _enabled_sources(self) -> list[str]:
        cfg = getattr(self.settings, "sanctions", None)
        configured = getattr(cfg, "sources", None) if cfg else None
        if isinstance(configured, dict):
            keys = [k for k, v in configured.items()
                    if v and k in SANCTIONS_SOURCES]
            if keys:
                return keys
        return list(SANCTIONS_SOURCES.keys())

    def _all_entries(self) -> list[dict[str, Any]]:
        """Return the combined, cached sanctions entries across all sources."""
        if self.cache:
            cached = self.cache.get(_CACHE_KEY)
            if cached:
                return list(cached)

        entries: list[dict[str, Any]] = []
        for kind in self._enabled_sources():
            label, url, parser = SANCTIONS_SOURCES[kind]
            resp = self.cached_get(url)
            if resp is None or resp.status_code != 200:
                logger.debug("[sanctions] {} list unavailable", kind)
                continue
            parsed = parse_source(parser, resp.text)
            logger.debug("[sanctions] {} entries from {}", len(parsed), label)
            entries.extend(parsed)

        if self.cache and entries:
            self.cache.set(_CACHE_KEY, entries)
        return entries

    # ------------------------------------------------------------------
    # Matching
    # ------------------------------------------------------------------
    @staticmethod
    def _normalise_name(name: str) -> str:
        name = normalize_text(name).lower()
        # Keep unicode word characters, collapse everything else to spaces.
        cleaned = "".join(ch if (ch.isalnum() or ch.isspace()) else " "
                          for ch in name)
        return " ".join(cleaned.split())

    def _candidate_forms(self, target: str) -> set[str]:
        """All normalised name forms to match against, incl. romanisation.

        Every base form (raw + romanised) is expanded into common
        name-order/initial permutations so "Kim Jong Un" also matches
        "Un Kim Jong", "Kim J U", "K Un", etc.
        """
        forms: set[str] = set()
        for base in (target, romanize(target)):
            norm = self._normalise_name(base)
            if norm:
                forms.add(norm)
                forms.update(self._permutations(norm))
        return {f for f in forms if f}

    @staticmethod
    def _permutations(norm: str) -> set[str]:
        """Common name-order / initial variants of a normalised name."""
        tokens = norm.split()
        if len(tokens) < 2:
            return set()
        out = {
            " ".join(reversed(tokens)),          # un kim jong
            f"{tokens[-1]} {tokens[0]}",         # last first
            f"{tokens[0]} {tokens[-1]}",         # first last (drop middles)
            f"{tokens[0][0]} {tokens[-1]}",      # initial + last
            " ".join([tokens[0]] + [t[0] for t in tokens[1:]]),  # first + inits
        }
        return {o for o in out if o}

    @staticmethod
    def _score(a: str, b: str) -> float:
        if not a or not b:
            return 0.0
        if a == b:
            return 1.0
        at, bt = a.split(), b.split()
        # Whole-token containment: "kim jong un" vs "kim jong un jr" is a strong
        # match, but a tiny initial form like "f li" must NOT match
        # "shelf limited" merely because those letters appear in sequence. The
        # old raw-substring rule produced absurd 0.92 entity matches.
        if set(at) <= set(bt) or set(bt) <= set(at):
            return 0.92
        ratio = difflib.SequenceMatcher(None, a, b).ratio()
        if at and bt:
            jaccard = len(set(at) & set(bt)) / len(set(at) | set(bt))
            ratio = max(ratio, jaccard)
        return ratio

    @staticmethod
    def _phonetic_score(a: str, b: str) -> float:
        """Metaphone-based similarity (catches transliteration variants).

        Uses the optional ``jellyfish`` package; returns 0.0 when it is not
        installed, so matching simply falls back to the string heuristics.
        """
        try:
            import jellyfish  # type: ignore
        except ImportError:
            return 0.0
        try:
            ta = {jellyfish.metaphone(w) for w in a.split() if w.isalpha()}
            tb = {jellyfish.metaphone(w) for w in b.split() if w.isalpha()}
        except Exception:  # noqa: BLE001 - jellyfish can raise on odd input
            return 0.0
        if not ta or not tb:
            return 0.0
        return 0.85 * (len(ta & tb) / len(ta | tb))

    def _match(self, target: str, entries: list[dict[str, Any]],
               threshold: float) -> list[tuple[float, dict[str, Any]]]:
        forms = self._candidate_forms(target)
        cfg = getattr(self.settings, "sanctions", None)
        use_phonetic = bool(getattr(cfg, "phonetic", True)) if cfg else True
        scored: list[tuple[float, dict[str, Any]]] = []
        for entry in entries:
            ename = self._normalise_name(entry.get("name", ""))
            if not ename:
                continue
            best = max((self._score(f, ename) for f in forms), default=0.0)
            if use_phonetic and best < threshold:
                best = max(best, max((self._phonetic_score(f, ename)
                                      for f in forms), default=0.0))
            if best >= threshold:
                scored.append((round(best, 3), entry))
        scored.sort(key=lambda t: t[0], reverse=True)
        return scored

    def _filter_sources(self, entries: list[dict[str, Any]],
                        source: Any) -> list[dict[str, Any]]:
        if not source:
            return entries
        keys = source if isinstance(source, (list, tuple, set)) else [source]
        labels = {SANCTIONS_SOURCES[k][0] for k in keys if k in SANCTIONS_SOURCES}
        if not labels:
            return entries
        return [e for e in entries if e.get("list") in labels]

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------
    def _opensanctions_key(self) -> str | None:
        import os
        cfg = getattr(self.settings, "sanctions", None)
        key = getattr(cfg, "opensanctions_key", None) if cfg else None
        return key or os.environ.get("RESEARCH_OPENSANCTIONS_KEY")

    def _want_opensanctions_bulk(self, source: Any) -> bool:
        """True when the key-free OpenSanctions bulk datasets should load."""
        cfg = getattr(self.settings, "sanctions", None)
        if cfg is None or not getattr(cfg, "opensanctions_bulk", False):
            return False
        if not getattr(cfg, "opensanctions", True):
            return False
        if self._opensanctions_key():
            return False   # the API path is preferred when a key is present
        if not source:
            return True
        keys = source if isinstance(source, (list, tuple, set)) else [source]
        return "opensanctions" in keys or "os" in keys

    def _opensanctions_bulk_entries(self) -> list[dict[str, Any]]:
        """Download + cache OpenSanctions bulk datasets (no API key needed)."""
        if self.cache:
            cached = self.cache.get(_OS_BULK_CACHE_KEY)
            if cached:
                return list(cached)
        entries: list[dict[str, Any]] = []
        timeout = max(self.settings.http.timeout, 60)
        for dataset in _BULK_DATASETS:
            url = _OPEN_SANCTIONS_BULK.format(dataset=dataset)
            try:
                resp = self.session.get(url, timeout=timeout)
            except Exception as exc:  # noqa: BLE001 - network errors vary
                logger.debug("[sanctions] bulk {} failed: {}", dataset, exc)
                continue
            if resp.status_code != 200:
                logger.debug("[sanctions] bulk {} HTTP {}", dataset,
                             resp.status_code)
                continue
            parsed = parse_opensanctions_bulk(resp.text)
            logger.debug("[sanctions] {} entries from bulk {}",
                         len(parsed), dataset)
            entries.extend(parsed)
        if self.cache and entries:
            self.cache.set(_OS_BULK_CACHE_KEY, entries)
        return entries

    def _want_opensanctions(self, source: Any) -> bool:
        cfg = getattr(self.settings, "sanctions", None)
        if cfg is not None and not getattr(cfg, "opensanctions", True):
            return False
        # The API requires a (free) key; skip cleanly when none is configured.
        if not self._opensanctions_key():
            return False
        if not source:
            return True
        keys = source if isinstance(source, (list, tuple, set)) else [source]
        return "opensanctions" in keys or "os" in keys

    def _opensanctions(self, target: str,
                       limit: int) -> tuple[list[Finding], bool]:
        """Query the OpenSanctions aggregated API. Returns ``(findings, ok)``.

        Requires a free API key (``RESEARCH_OPENSANCTIONS_KEY``). ``ok`` is
        ``False`` when the API could not be reached (e.g. 401/403/network), so
        the caller can distinguish "no match" from "source unavailable".
        """
        params = urlencode({"q": target, "limit": limit})
        headers = {"Accept": "application/json",
                   "Authorization": f"ApiKey {self._opensanctions_key()}"}
        resp = self.cached_get(f"{_OPEN_SANCTIONS_URL}?{params}", headers=headers)
        if resp is None or resp.status_code != 200:
            logger.debug("[sanctions] OpenSanctions unavailable (status={})",
                         getattr(resp, "status_code", "n/a"))
            return [], False
        try:
            data = resp.json()
        except ValueError:
            return [], False
        if not isinstance(data, dict):
            return [], False
        findings: list[Finding] = []
        for item in (data.get("results") or [])[:limit]:
            score = float(item.get("score") or 0.0)
            datasets = item.get("datasets") or []
            ent_id = item.get("id")
            findings.append(self.finding(
                title=f"OpenSanctions match ({score:.2f}): {item.get('caption')}",
                detail=(f"schema={item.get('schema')}, "
                        f"datasets={', '.join(datasets[:6]) or 'n/a'}"),
                url=(f"https://www.opensanctions.org/entities/{ent_id}/"
                     if ent_id else None),
                confidence=score or 0.6, category="sanctions", status="matched",
                sanctions_list="OpenSanctions", datasets=datasets,
                entity_schema=item.get("schema"), match_score=score,
                matched_name=item.get("caption"),
            ))
        return findings, True

    def run(self, target: str, *, source: Any = None,
            threshold: float = DEFAULT_THRESHOLD, limit: int = 10,
            **kwargs: Any) -> list[Finding]:
        """Screen *target* against the configured sanctions lists."""
        target = (target or "").strip()
        if not target:
            return []

        findings: list[Finding] = []

        # 1. Local static lists (OFAC / UN / EU / UK), fuzzy + phonetic match.
        entries = self._filter_sources(self._all_entries(), source)
        # 1b. Key-free OpenSanctions bulk data (opt-in; augments local lists).
        if self._want_opensanctions_bulk(source):
            entries = entries + self._filter_sources(
                self._opensanctions_bulk_entries(), source)
        for score, entry in self._match(target, entries, threshold)[:limit]:
            findings.append(self.finding(
                title=f"Sanctions match ({score:.2f}): {entry.get('name')}",
                detail=(
                    f"list={entry.get('list')}, "
                    f"program={entry.get('program') or 'n/a'}, "
                    f"type={entry.get('type') or 'n/a'}, "
                    f"id={entry.get('id') or 'n/a'}"
                ),
                confidence=score, category="sanctions", status="matched",
                sanctions_list=entry.get("list"), program=entry.get("program"),
                entity_type=entry.get("type"), reference_id=entry.get("id"),
                match_score=score, matched_name=entry.get("name"),
            ))

        # 2. OpenSanctions aggregated API (100+ lists incl. DPRK/Russia/Iran).
        os_ok = False
        if self._want_opensanctions(source):
            os_findings, os_ok = self._opensanctions(target, limit)
            findings.extend(os_findings)

        if findings:
            logger.info("[sanctions] {} match(es) for '{}'",
                        len(findings), target)
            return findings
        if not entries and not os_ok:
            return [self.finding(
                title="Sanctions data unavailable",
                detail=("No sanctions list or API could be reached. Check the "
                        "network/proxy; sources are treasury.gov, un.org, "
                        "europa.eu, gov.uk and api.opensanctions.org."),
                confidence=0.2, status="skipped",
            )]
        return [self.finding(
            title=f"No sanctions match for '{target}'",
            detail=(f"Screened against {len(entries)} list entries"
                    + (" + OpenSanctions" if os_ok else "")
                    + f"; no name matched at >= {threshold}."),
            confidence=0.6, status="not_found",
        )]


__all__ = [
    "SanctionsEngine", "SANCTIONS_SOURCES", "DEFAULT_THRESHOLD",
    "parse_source", "parse_ofac", "parse_un", "parse_eu", "parse_uk",
    "parse_opensanctions_bulk",
]