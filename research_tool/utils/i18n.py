"""Internationalisation (i18n) helpers for cross-border research.

This module lets the toolkit work across languages and writing systems,
which is essential when researching targets in restricted or non-English
regions (e.g. the DPRK, China, Russia, Iran):

  * **script / language detection** - classify text as Hangul, Han, Cyrillic,
    Arabic, ... and (best-effort) resolve an ISO-639-1 language code;
  * **romanisation** - transliterate Hangul, Cyrillic, Greek and Arabic to
    Latin so a Korean/Cyrillic name can also be searched on Western engines;
  * **query expansion** - turn one target into several script/language
    variants so the same person/entity can be searched across regions;
  * **translation** - optional machine translation via a self-hosted or
    public LibreTranslate endpoint, or MyMemory (no key required);
  * **normalisation** - Unicode NFKC folding and zero-width stripping so
    scraped CJK/Cyrillic/Arabic text is compared consistently.

Every capability degrades gracefully: detection falls back to Unicode
script ranges, romanisation uses built-in tables, and translation simply
returns ``None`` when no backend is reachable. Nothing here raises on
malformed input.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Iterable
from urllib.parse import urlencode

from ..logger import logger

# --------------------------------------------------------------------------
# Script detection - Unicode code-point ranges
# --------------------------------------------------------------------------
_SCRIPT_RANGES: list[tuple[str, int, int]] = [
    ("hangul", 0xAC00, 0xD7A3),      # Hangul syllables
    ("hangul", 0x1100, 0x11FF),      # Hangul Jamo
    ("kana", 0x3040, 0x30FF),        # Hiragana + Katakana
    ("han", 0x4E00, 0x9FFF),         # CJK Unified Ideographs
    ("han", 0x3400, 0x4DBF),         # CJK Extension A
    ("cyrillic", 0x0400, 0x04FF),    # Cyrillic
    ("cyrillic", 0x0500, 0x052F),    # Cyrillic Supplement
    ("arabic", 0x0600, 0x06FF),      # Arabic
    ("arabic", 0x0750, 0x077F),      # Arabic Supplement
    ("arabic", 0xFB50, 0xFDFF),      # Arabic Presentation Forms-A
    ("hebrew", 0x0590, 0x05FF),      # Hebrew
    ("thai", 0x0E00, 0x0E7F),        # Thai
    ("devanagari", 0x0900, 0x097F),  # Devanagari (Hindi etc.)
    ("greek", 0x0370, 0x03FF),       # Greek
]

# script -> a reasonable default ISO-639-1 language (used when langdetect
# is unavailable or returns nothing).
_SCRIPT_LANGUAGE: dict[str, str] = {
    "hangul": "ko",
    "kana": "ja",
    "han": "zh",
    "cyrillic": "ru",
    "arabic": "ar",
    "hebrew": "he",
    "thai": "th",
    "devanagari": "hi",
    "greek": "el",
    "latin": "en",
}

# A few very common words that disambiguate languages sharing a script.
_LANGUAGE_HINTS: dict[str, tuple[str, ...]] = {
    "ar": ("ال", "من", "في", "على", "هو"),
    "fa": ("است", "که", "این", "برای", "ایران"),
    "ru": ("и", "в", "на", "не", "что"),
    "uk": ("і", "та", "що", "це", "не"),
    "el": ("και", "το", "της", "είναι"),
}


def _script_counts(text: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for ch in text:
        code = ord(ch)
        for name, lo, hi in _SCRIPT_RANGES:
            if lo <= code <= hi:
                counts[name] = counts.get(name, 0) + 1
                break
        else:
            if ch.isalpha():
                counts["latin"] = counts.get("latin", 0) + 1
    return counts


def detect_script(text: str) -> str:
    """Return the dominant writing system of *text*.

    One of ``hangul``, ``kana``, ``han``, ``cyrillic``, ``arabic``,
    ``hebrew``, ``thai``, ``devanagari``, ``greek`` or ``latin``. Returns
    ``"unknown"`` for empty/uncategorised input.
    """
    text = text or ""
    counts = _script_counts(text)
    if not counts:
        return "unknown"
    # Kana + Han means Japanese; prefer the kana signal for the script name.
    if counts.get("kana"):
        return "kana"
    return max(counts.items(), key=lambda kv: kv[1])[0]


def detect_language(text: str) -> str:
    """Best-effort ISO-639-1 language code for *text*.

    Uses the optional ``langdetect`` library when available for finer
    resolution, otherwise falls back to Unicode-script heuristics (with a
    few common-word hints to separate languages that share a script).
    """
    text = (text or "").strip()
    if not text:
        return "und"

    # Prefer a full statistical detector when installed.
    try:
        from langdetect import detect  # type: ignore
        try:
            code = detect(text)
            if code:
                return code
        except Exception:  # noqa: BLE001 - langdetect raises on short input
            pass
    except ImportError:
        pass

    script = detect_script(text)
    lowered = text.lower()
    for lang, hints in _LANGUAGE_HINTS.items():
        if any(h in lowered for h in hints):
            return lang
    return _SCRIPT_LANGUAGE.get(script, "und")


def script_language(script: str) -> str:
    """Default language code associated with a writing system."""
    return _SCRIPT_LANGUAGE.get(script, "und")


# --------------------------------------------------------------------------
# Romanisation - built-in transliteration tables (no dependency required)
# --------------------------------------------------------------------------
# Korean - Revised Romanization, built from the Hangul syllable algorithm.
_HANGUL_CHO = ["g", "kk", "n", "d", "tt", "r", "m", "b", "pp", "s", "ss",
               "", "j", "jj", "ch", "k", "t", "p", "h"]
_HANGUL_JUNG = ["a", "ae", "ya", "yae", "eo", "e", "yeo", "ye", "o", "wa",
                "wae", "oe", "yo", "u", "wo", "we", "wi", "yu", "eu", "ui", "i"]
_HANGUL_JONG = ["", "k", "k", "k", "n", "n", "n", "t", "l", "k", "m", "l",
                "l", "l", "p", "l", "m", "p", "p", "t", "t", "ng", "t", "t",
                "k", "t", "p", "t"]

# Cyrillic (Russian-centric; also fine for Ukrainian/Bulgarian names).
_CYRILLIC: dict[str, str] = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "shch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
    "і": "i", "ї": "yi", "є": "ye", "ґ": "g",
}

# Greek.
_GREEK: dict[str, str] = {
    "α": "a", "β": "v", "γ": "g", "δ": "d", "ε": "e", "ζ": "z", "η": "i",
    "θ": "th", "ι": "i", "κ": "k", "λ": "l", "μ": "m", "ν": "n", "ξ": "x",
    "ο": "o", "π": "p", "ρ": "r", "σ": "s", "ς": "s", "τ": "t", "υ": "y",
    "φ": "f", "χ": "ch", "ψ": "ps", "ω": "o",
    # accented / diaeresis vowels (Modern Greek)
    "ά": "a", "έ": "e", "ή": "i", "ί": "i", "ό": "o", "ύ": "y", "ώ": "o",
    "ϊ": "i", "ϋ": "y", "ΐ": "i", "ΰ": "y",
}

# Arabic (simplified; good enough for searching Latin-script engines).
_ARABIC: dict[str, str] = {
    "ا": "a", "أ": "a", "إ": "i", "آ": "a", "ب": "b", "ت": "t", "ث": "th",
    "ج": "j", "ح": "h", "خ": "kh", "د": "d", "ذ": "dh", "ر": "r", "ز": "z",
    "س": "s", "ش": "sh", "ص": "s", "ض": "d", "ط": "t", "ظ": "z", "ع": "'",
    "غ": "gh", "ف": "f", "ق": "q", "ك": "k", "ل": "l", "م": "m", "ن": "n",
    "ه": "h", "و": "w", "ي": "y", "ى": "a", "ة": "a", "ء": "'", "ئ": "'",
    "ؤ": "'",
}


def _romanise_hangul(text: str) -> str:
    out: list[str] = []
    for ch in text:
        code = ord(ch) - 0xAC00
        if 0 <= code < 11172:
            cho = code // 588
            jung = (code % 588) // 28
            jong = code % 28
            out.append(_HANGUL_CHO[cho] + _HANGUL_JUNG[jung] + _HANGUL_JONG[jong])
        else:
            out.append(ch)
    return "".join(out)


def _romanise_table(text: str, table: dict[str, str]) -> str:
    out: list[str] = []
    for ch in text:
        lower = ch.lower()
        if lower in table:
            rom = table[lower]
            out.append(rom.upper() if ch.isupper() and rom else rom)
        else:
            out.append(ch)
    return "".join(out)


def romanize(text: str) -> str:
    """Transliterate *text* to Latin script using built-in tables.

    Handles Hangul (Revised Romanization), Cyrillic, Greek and Arabic.
    Text already in Latin script is returned unchanged.
    """
    text = text or ""
    if not text:
        return ""
    script = detect_script(text)
    if script == "hangul":
        return _romanise_hangul(text)
    if script == "cyrillic":
        return _romanise_table(text, _CYRILLIC)
    if script == "greek":
        return _romanise_table(text, _GREEK)
    if script == "arabic":
        return _romanise_table(text, _ARABIC)
    return text


def normalize_text(text: str) -> str:
    """NFKC-fold and strip zero-width/invisible characters from *text*."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    return re.sub(r"[\u200b-\u200f\u202a-\u202e\ufeff]", "", text).strip()


# --------------------------------------------------------------------------
# Translation - optional, backend-agnostic, degrades to None
# --------------------------------------------------------------------------
# Languages the toolkit expands a Latin target into by default. Chosen for
# restricted / non-English regions where in-country sources matter most.
DEFAULT_TARGET_LANGUAGES: list[str] = ["ko", "zh-CN", "ru", "ar", "fa"]

_MYMEMORY_URL = "https://api.mymemory.translated.net/get"
_LIBRE_TRANSLATE_URL = "https://libretranslate.com/translate"
# Unofficial Google Translate endpoints (no key). The lightweight JSON
# endpoint is tried first; the /m HTML page is the fallback.
_GOOGLE_JSON_URL = "https://translate.googleapis.com/translate_a/single"
_GOOGLE_TRANSLATE_URL = "https://translate.google.com/m"


class Translator:
    """Best-effort machine translation with graceful degradation.

    Backends, tried in order of the ``backend`` setting:

      * ``deepl`` - DeepL (requires ``deepl_key`` / ``RESEARCH_DEEPL_KEY``);
      * ``libretranslate`` - a self-hosted or public LibreTranslate endpoint
        (``POST {url}/translate``); set ``libretranslate_url`` for your own;
      * ``google`` - Google's unofficial mobile endpoint (no key, far less
        rate-limited than MyMemory);
      * ``mymemory`` - the free MyMemory GET API (no key required).

    Any network/format error returns ``None`` rather than raising, so callers
    can simply skip a language that could not be translated.
    """

    def __init__(self, *, backend: str = "auto", session: Any | None = None,
                 libretranslate_url: str | None = None,
                 deepl_key: str | None = None, timeout: int = 20,
                 cache: Any | None = None):
        self.backend = backend
        self.session = session
        self.libretranslate_url = libretranslate_url
        self.deepl_key = deepl_key
        self.timeout = timeout
        self.cache = cache

    # ------------------------------------------------------------------
    def _get_session(self) -> Any | None:
        if self.session is not None:
            return self.session
        try:
            import requests
            self.session = requests.Session()
            self.session.headers.update(
                {"User-Agent": "Mozilla/5.0 ResearchTool/1.0"}
            )
        except ImportError:  # pragma: no cover - requests is a hard dep
            return None
        return self.session

    def _backends(self) -> list[str]:
        if self.backend != "auto":
            return [self.backend]
        order: list[str] = []
        if self.deepl_key:
            order.append("deepl")
        if self.libretranslate_url:
            order.append("libretranslate")
        # Google (unofficial) is far less rate-limited than MyMemory.
        order.append("google")
        order.append("mymemory")
        return order

    # ------------------------------------------------------------------
    def translate(self, text: str, target: str, source: str = "auto") -> str | None:
        """Translate *text* into *target* (ISO-639-1). ``None`` on failure."""
        text = (text or "").strip()
        if not text:
            return None
        if source == "auto":
            source = detect_language(text)
        # Normalise region codes for backends that want the bare language.
        target_norm = target.split("-")[0].lower()
        if source and source.split("-")[0].lower() == target_norm:
            return text

        cache_key = f"i18n translate {source}->{target_norm} {text}"
        if self.cache:
            cached = self.cache.get(cache_key)
            if cached is not None:
                return cached

        session = self._get_session()
        if session is None:
            return None
        for backend in self._backends():
            try:
                result = self._call(backend, session, text, target_norm, source)
            except Exception as exc:  # noqa: BLE001 - any backend may fail
                logger.debug("[i18n] {} translate failed: {}", backend, exc)
                result = None
            if result:
                if self.cache:
                    self.cache.set(cache_key, result)
                return result
        return None

    def _call(self, backend: str, session: Any, text: str,
              target: str, source: str) -> str | None:
        if backend == "libretranslate":
            return self._libretranslate(session, text, target, source)
        if backend == "deepl":
            return self._deepl(session, text, target, source)
        if backend == "google":
            return self._google(session, text, target, source)
        if backend == "mymemory":
            return self._mymemory(session, text, target, source)
        return None

    def _google(self, session: Any, text: str, target: str,
                source: str) -> str | None:
        """Translate via Google's unofficial endpoints (no key).

        Tries the lightweight ``translate_a/single`` JSON API first (most
        reliable, returns a nested-array translation), then the ``/m`` HTML
        page as a fallback.
        """
        # 1. JSON endpoint: [[["translated","source",...],...],...]
        params = urlencode({"client": "gtx", "sl": source or "auto",
                            "tl": target, "dt": "t", "q": text})
        resp = session.get(f"{_GOOGLE_JSON_URL}?{params}", timeout=self.timeout)
        if resp.status_code == 200:
            try:
                data = resp.json()
                segments = data[0] or []
                translated = "".join(seg[0] for seg in segments
                                     if seg and seg[0])
                if translated.strip():
                    return translated.strip()
            except (ValueError, TypeError, IndexError, KeyError):
                pass

        # 2. HTML fallback.
        params = urlencode({"sl": source or "auto", "tl": target, "q": text})
        resp = session.get(f"{_GOOGLE_TRANSLATE_URL}?{params}",
                           timeout=self.timeout)
        if resp.status_code != 200:
            return None
        match = re.search(r'class="result-container">(.*?)</div>',
                          resp.text, re.DOTALL)
        if not match:
            return None
        from html import unescape
        translated = unescape(match.group(1)).strip()
        return translated or None

    def _libretranslate(self, session: Any, text: str, target: str,
                        source: str) -> str | None:
        url = (self.libretranslate_url or _LIBRE_TRANSLATE_URL).rstrip("/")
        if not url.endswith("/translate"):
            url = f"{url}/translate"
        resp = session.post(
            url,
            json={"q": text, "source": source or "auto",
                  "target": target, "format": "text"},
            timeout=self.timeout,
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        return (data.get("translatedText") or "").strip() or None

    def _mymemory(self, session: Any, text: str, target: str,
                  source: str) -> str | None:
        params = urlencode({"q": text, "langpair": f"{source or 'en'}|{target}"})
        resp = session.get(f"{_MYMEMORY_URL}?{params}", timeout=self.timeout)
        if resp.status_code != 200:
            return None
        data = resp.json()
        translated = (data.get("responseData") or {}).get("translatedText")
        if not translated:
            return None
        # MyMemory echoes quota errors as the "translation".
        if "MYMEMORY WARNING" in translated.upper():
            return None
        return translated.strip() or None

    def _deepl(self, session: Any, text: str, target: str,
               source: str) -> str | None:
        if not self.deepl_key:
            return None
        url = "https://api-free.deepl.com/v2/translate"
        resp = session.post(
            url,
            headers={"Authorization": f"DeepL-Auth-Key {self.deepl_key}"},
            data={"text": text, "target_lang": target.upper(),
                  "source_lang": (source or "").upper() or None},
            timeout=self.timeout,
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        translations = data.get("translations") or []
        if translations:
            return (translations[0].get("text") or "").strip() or None
        return None


# --------------------------------------------------------------------------
# Query expansion
# --------------------------------------------------------------------------
@dataclass
class QueryVariant:
    """A single search query in a specific language / script."""

    text: str
    language: str
    method: str            # original | romanized | translated
    script: str = "latin"

    def as_dict(self) -> dict[str, str]:
        return {"text": self.text, "language": self.language,
                "method": self.method, "script": self.script}


def generate_query_variants(
    target: str,
    target_languages: Iterable[str] | None = None,
    translator: Translator | None = None,
    *,
    include_romanized: bool = True,
) -> list[QueryVariant]:
    """Expand *target* into searchable variants across languages/scripts.

    Always returns the original (normalised) target first. For a non-Latin
    target a romanised variant is added so Western engines can be queried
    too; when a :class:`Translator` is supplied, one translated variant is
    produced per language in *target_languages*.
    """
    target = normalize_text(target)
    if not target:
        return []

    langs = list(target_languages) if target_languages else list(DEFAULT_TARGET_LANGUAGES)
    variants: list[QueryVariant] = []
    seen: set[str] = {target}

    src_lang = detect_language(target)
    src_script = detect_script(target)
    variants.append(QueryVariant(target, src_lang, "original", src_script))

    # Romanisation for non-Latin scripts (helps Western engines).
    if include_romanized and src_script not in ("latin", "unknown"):
        rom = romanize(target).strip()
        if rom and rom not in seen:
            seen.add(rom)
            variants.append(QueryVariant(rom, src_lang, "romanized", "latin"))

    # Translations into each requested language.
    if translator is not None:
        for lang in langs:
            translated = translator.translate(target, target=lang, source=src_lang)
            if not translated or translated in seen:
                continue
            seen.add(translated)
            variants.append(QueryVariant(
                translated, lang, "translated", detect_script(translated),
            ))
    return variants


def translator_from_settings(settings: Any, session: Any | None = None,
                             cache: Any | None = None) -> Translator | None:
    """Build a :class:`Translator` from the ``i18n`` config, or ``None``.

    Returns ``None`` when i18n is disabled or set to the ``none`` backend,
    so callers can cheaply skip translation.
    """
    cfg = getattr(settings, "i18n", None)
    if cfg is None or not getattr(cfg, "enabled", True):
        return None
    backend = getattr(cfg, "translation_backend", "auto")
    if backend in (None, "none"):
        return None
    import os
    return Translator(
        backend=backend,
        session=session,
        libretranslate_url=getattr(cfg, "libretranslate_url", None),
        deepl_key=getattr(cfg, "deepl_key", None) or os.environ.get("RESEARCH_DEEPL_KEY"),
        cache=cache,
    )


__all__ = [
    "detect_script", "detect_language", "script_language",
    "romanize", "normalize_text",
    "Translator", "QueryVariant", "generate_query_variants",
    "translator_from_settings", "DEFAULT_TARGET_LANGUAGES",
]
