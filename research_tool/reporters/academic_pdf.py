"""Academic typesetting: Markdown manuscripts rendered as research-paper PDFs.

The toolkit's earlier PDF writer dumped engine records into ``Paragraph``
objects, which produced documents nobody could read: ``engine=... |
category=...`` debug lines, raw Markdown pipe tables and bare URLs interleaved
with prose.

This module is the publication-grade replacement. It renders a *manuscript*
(a small, well-defined Markdown subset) using standard research-paper
conventions:

* a formal title block (title, subtitle, author, date, keywords);
* a shaded abstract box;
* justified serif body text with numbered headings;
* booktabs-style data tables that split across pages and wrap long cells;
* bullet/numbered lists, callouts (blockquotes), and code blocks;
* a running header, a footer with "Page X of Y", and a formal reference list
  (hanging indent) when a ``References`` section is present.

Fonts are Unicode TrueType when available (Times New Roman / Arial on Windows,
DejaVu or Liberation on Linux, or a directory named by
``RESEARCH_PDF_FONT_DIR``), so Vietnamese diacritics, arrows and dashes render
correctly. Core PDF fonts are used only as a last resort.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from typing import Sequence
from xml.sax.saxutils import escape as _xml_escape

from ..utils.validators import safe_href

# Candidate font files per role: (regular, bold, italic, bold-italic).
_FONT_SETS: tuple[tuple[str, tuple[str, str, str, str]], ...] = (
    ("RTimes", ("times.ttf", "timesbd.ttf", "timesi.ttf", "timesbi.ttf")),
    ("RDejaVuSerif", ("DejaVuSerif.ttf", "DejaVuSerif-Bold.ttf",
                      "DejaVuSerif-Italic.ttf", "DejaVuSerif-BoldItalic.ttf")),
    ("RLiberationSerif", ("LiberationSerif-Regular.ttf",
                          "LiberationSerif-Bold.ttf",
                          "LiberationSerif-Italic.ttf",
                          "LiberationSerif-BoldItalic.ttf")),
)
_SANS_SETS: tuple[tuple[str, tuple[str, str, str, str]], ...] = (
    ("RSans", ("arial.ttf", "arialbd.ttf", "ariali.ttf", "arialbi.ttf")),
    ("RDejaVuSans", ("DejaVuSans.ttf", "DejaVuSans-Bold.ttf",
                     "DejaVuSans-Oblique.ttf", "DejaVuSans-BoldOblique.ttf")),
    ("RLiberationSans", ("LiberationSans-Regular.ttf",
                         "LiberationSans-Bold.ttf",
                         "LiberationSans-Italic.ttf",
                         "LiberationSans-BoldItalic.ttf")),
)
# CJK / Hangul / kana fallback. Microsoft YaHei covers Chinese and Japanese
# kana; Malgun Gothic covers Hangul. SimSun / MS Gothic / Batang are used when
# the preferred file is absent.
_CJK_SETS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("RCJK", ("msyh.ttc", "msyh.ttf", "NotoSansCJKsc-Regular.otf",
              "NotoSansCJK-Regular.ttc")),
    ("RCJK", ("simsun.ttc", "simsunb.ttf", "simhei.ttf", "wqy-zenhei.ttc")),
    ("RCJK", ("msgothic.ttc", "meiryo.ttc")),
)
_KOREAN_SETS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("RCJKKR", ("malgun.ttf",)),
    ("RCJKKR", ("batang.ttc", "gulim.ttc", "NotoSansCJKkr-Regular.otf")),
)


def _font_directories() -> list[Path]:
    """Folders searched for TrueType fonts, in priority order."""
    dirs: list[Path] = []
    override = os.environ.get("RESEARCH_PDF_FONT_DIR")
    if override:
        dirs.append(Path(override))
    windir = os.environ.get("WINDIR") or os.environ.get("SystemRoot")
    if windir:
        dirs.append(Path(windir) / "Fonts")
    dirs += [Path("/usr/share/fonts"), Path("/usr/local/share/fonts"),
             Path.home() / ".fonts", Path("/Library/Fonts"),
             Path("/System/Library/Fonts")]
    return dirs


@dataclass(frozen=True)
class FontSet:
    """Resolved font family names for body text, tables and CJK fallback."""

    body: str
    sans: str
    mono: str
    cjk: str | None = None
    hangul: str | None = None


@lru_cache(maxsize=1)
def register_fonts() -> FontSet:
    """Register Unicode TrueType families and return their names."""
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    directories = [d for d in _font_directories() if d.is_dir()]

    def find(names: Sequence[str]) -> Path | None:
        for directory in directories:
            for name in names:
                candidate = directory / name
                if candidate.is_file():
                    return candidate
        return None

    def register(family: str, files: Sequence[str]) -> str | None:
        paths = [find([name]) for name in files]
        regular = paths[0]
        if regular is None:
            return None
        pdfmetrics.registerFont(TTFont(family, str(regular)))
        for suffix, path in zip(("Bold", "Italic", "BoldItalic"), paths[1:]):
            if path:
                pdfmetrics.registerFont(TTFont(f"{family}-{suffix}", str(path)))
        pdfmetrics.registerFontFamily(
            family,
            normal=family,
            bold=f"{family}-Bold" if paths[1] else family,
            italic=f"{family}-Italic" if paths[2] else family,
            boldItalic=(f"{family}-BoldItalic" if paths[3]
                        else f"{family}-Bold" if paths[1] else family),
        )
        return family

    body = next((name for name, files in _FONT_SETS
                 if register(name, files)), "Times-Roman")
    sans = next((name for name, files in _SANS_SETS
                 if register(name, files)), "Helvetica")
    mono = "Courier"
    courier = find(["cour.ttf"])
    if courier:
        pdfmetrics.registerFont(TTFont("RCourier", str(courier)))
        mono = "RCourier"
    def register_fallback(
        groups: Sequence[tuple[str, Sequence[str]]]
    ) -> str | None:
        """Register the first available font in *groups*; return its family."""
        for family, names in groups:
            path = find(list(names))
            if path is None:
                continue
            if path.suffix.lower() in (".ttc", ".otc"):   # TrueType collection
                for index in (0, 1, 2):
                    try:
                        pdfmetrics.registerFont(
                            TTFont(family, str(path), subfontIndex=index))
                        return family
                    except (OSError, ValueError, KeyError, IndexError):
                        continue
            else:
                try:
                    pdfmetrics.registerFont(TTFont(family, str(path)))
                    return family
                except (OSError, ValueError):
                    continue
        return None

    cjk = register_fallback(_CJK_SETS)
    hangul = register_fallback(_KOREAN_SETS)
    return FontSet(body=body, sans=sans, mono=mono, cjk=cjk, hangul=hangul)
# ---------------------------------------------------------------------------
# Styles
# ---------------------------------------------------------------------------
def build_styles():
    """Return the flowable styles used for a manuscript PDF."""
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
    from reportlab.lib.styles import ParagraphStyle

    fonts = register_fonts()
    ink = colors.HexColor("#1a1a1a")
    muted = colors.HexColor("#555555")
    accent = colors.HexColor("#0b3d6b")

    def style(name: str, **kwargs) -> ParagraphStyle:
        return ParagraphStyle(name, **kwargs)

    return {
        "title": style("RTitle", fontName=fonts.body, fontSize=19, leading=23,
                       alignment=TA_LEFT, textColor=ink, spaceAfter=4),
        "subtitle": style("RSubtitle", fontName=fonts.body, fontSize=12.5,
                          leading=16, alignment=TA_LEFT, textColor=accent,
                          spaceAfter=6),
        "meta": style("RMeta", fontName=fonts.sans, fontSize=8.6, leading=12,
                      alignment=TA_LEFT, textColor=muted, spaceAfter=2),
        "keywords": style("RKeywords", fontName=fonts.body, fontSize=9,
                          leading=12.5, alignment=TA_LEFT, textColor=ink,
                          spaceBefore=4, spaceAfter=2),
        "h1": style("RH1", fontName=fonts.body, fontSize=14, leading=17.5,
                    alignment=TA_LEFT, textColor=ink, spaceBefore=16,
                    spaceAfter=6, keepWithNext=1),
        "h2": style("RH2", fontName=fonts.body, fontSize=11.8, leading=15,
                    alignment=TA_LEFT, textColor=accent, spaceBefore=12,
                    spaceAfter=4, keepWithNext=1),
        "h3": style("RH3", fontName=fonts.body, fontSize=10.6, leading=13.6,
                    alignment=TA_LEFT, textColor=ink, spaceBefore=10,
                    spaceAfter=3, keepWithNext=1),
        "h4": style("RH4", fontName=fonts.sans, fontSize=9.6, leading=12.4,
                    alignment=TA_LEFT, textColor=muted, spaceBefore=8,
                    spaceAfter=2, keepWithNext=1),
        "body": style("RBody", fontName=fonts.body, fontSize=10.2, leading=14.4,
                      alignment=TA_JUSTIFY, textColor=ink, spaceAfter=5.5),
        "abstract": style("RAbstract", fontName=fonts.body, fontSize=9.6,
                          leading=13.6, alignment=TA_JUSTIFY, textColor=ink),
        "abstract_label": style("RAbstractLabel", fontName=fonts.sans,
                                fontSize=8.2, leading=10, alignment=TA_CENTER,
                                textColor=muted, spaceAfter=4),
        "bullet": style("RBullet", fontName=fonts.body, fontSize=10.2,
                        leading=14, alignment=TA_JUSTIFY, textColor=ink,
                        leftIndent=14, bulletIndent=2, spaceAfter=3,
                        bulletFontName=fonts.body, bulletFontSize=9),
        "numbered": style("RNumbered", fontName=fonts.body, fontSize=10.2,
                          leading=14, alignment=TA_JUSTIFY, textColor=ink,
                          leftIndent=18, bulletIndent=1, spaceAfter=3,
                          bulletFontName=fonts.body, bulletFontSize=9.6),
        "quote": style("RQuote", fontName=fonts.body, fontSize=9.6,
                       leading=13.4, alignment=TA_LEFT, textColor=muted,
                       leftIndent=12, rightIndent=8, spaceBefore=4,
                       spaceAfter=6),
        "table": style("RTable", fontName=fonts.body, fontSize=8.8,
                       leading=11.4, alignment=TA_LEFT, textColor=ink),
        "table_head": style("RTableHead", fontName=fonts.sans, fontSize=8.6,
                            leading=11.2, alignment=TA_LEFT, textColor=ink),
        "caption": style("RCaption", fontName=fonts.sans, fontSize=8.2,
                         leading=10.6, alignment=TA_LEFT, textColor=muted,
                         spaceBefore=2, spaceAfter=8),
        "reference": style("RReference", fontName=fonts.body, fontSize=9,
                           leading=12.4, alignment=TA_LEFT, textColor=ink,
                           leftIndent=16, firstLineIndent=-16, spaceAfter=3.5),
        "code": style("RCode", fontName=fonts.mono, fontSize=8.2, leading=10.6,
                      alignment=TA_LEFT, textColor=ink),
    }
# ---------------------------------------------------------------------------
# Inline Markdown -> ReportLab markup
# ---------------------------------------------------------------------------
_INLINE_RE = re.compile(
    r"`(?P<code>[^`]+)`"
    r"|\[(?P<label>[^\]]+)\]\((?P<href>[^)\s]+)\)"
    r"|<(?P<autolink>https?://[^>\s]+)>"
    r"|\*\*(?P<bold>[^*]+)\*\*"
    r"|(?:(?<=^)|(?<=[\s(\[]))\*(?P<italic>[^*\s][^*]*?)\*(?=[\s.,;:)\]]|$)"
    r"|(?:(?<=^)|(?<=[\s(\[]))_(?P<ital2>[^_\s][^_]*?)_(?=[\s.,;:)\]]|$)"
)


def _header_text(text: str) -> str:
    """Plain text for running heads and footers.

    Markdown emphasis markers are removed but underscores are kept, so a
    ``paper_id`` such as ``reign-of-nightfall-case-study_2026-11-21`` is printed
    intact in the page furniture.
    """
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", str(text))
    return re.sub(r"[*`#>~]+", "", text).strip()


def _esc(text: str) -> str:
    """Escape XML special characters while leaving Unicode intact."""
    return _xml_escape(str(text), {'"': "&quot;"})


# CJK ideographs, kana and full-width forms: the Latin body font has no glyphs
# for these, so runs are wrapped in the CJK fallback family.
_CJK_RE = re.compile(
    "[\u1100-\u11ff\u2e80-\u303f\u3040-\u30ff\u3130-\u318f"
    "\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af\uf900-\ufaff\uff00-\uffef]+")
_HAN_RE = re.compile(
    "[\u2e80-\u303f\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff"
    "\uf900-\ufaff\uff00-\uffef]+")
_HANGUL_RE = re.compile("[\u1100-\u11ff\u3130-\u318f\uac00-\ud7af]+")


def _cjk(text: str) -> str:
    """Wrap CJK/Hangul/kana runs in the matching fallback font.

    Hangul is routed to a Korean face (Microsoft YaHei has no Hangul glyphs)
    and everything else to the CJK face, so native-script references such as
    夜幕之下 or 김정은 render instead of extracting as null glyphs.
    """
    fonts = register_fonts()
    if not fonts.cjk or not _CJK_RE.search(text):
        return text
    if fonts.hangul:
        text = _HANGUL_RE.sub(
            lambda match: f'<font name="{fonts.hangul}">{match.group(0)}</font>',
            text)
    return _HAN_RE.sub(
        lambda match: f'<font name="{fonts.cjk}">{match.group(0)}</font>',
        text)


def inline_markup(text: str, *, code_size: float = 8.6) -> str:
    """Convert the supported inline Markdown subset to ReportLab markup."""
    out: list[str] = []
    last = 0
    for match in _INLINE_RE.finditer(text):
        out.append(_cjk(_esc(text[last:match.start()])))
        groups = match.groupdict()
        if groups.get("code") is not None:
            fonts = register_fonts()
            out.append(
                f'<font name="{fonts.mono}" size="{code_size}">'
                f'{_cjk(_esc(groups["code"]))}</font>')
        elif groups.get("label") is not None:
            out.append(
                f'<a href="{_esc(safe_href(groups["href"]))}" color="#0b3d6b">'
                f'{inline_markup(groups["label"], code_size=code_size)}</a>')
        elif groups.get("autolink") is not None:
            url = groups["autolink"]
            out.append(
                f'<a href="{_esc(safe_href(url))}" color="#0b3d6b">'
                f'{_esc(url)}</a>')
        elif groups.get("bold") is not None:
            out.append(
                f'<b>{inline_markup(groups["bold"], code_size=code_size)}</b>')
        else:
            text_in = groups.get("italic") or groups.get("ital2") or ""
            out.append(
                f'<i>{inline_markup(text_in, code_size=code_size)}</i>')
        last = match.end()
    out.append(_cjk(_esc(text[last:])))
    return "".join(out)


def strip_markdown(text: str) -> str:
    """Return plain text (used for titles and metadata labels)."""
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", str(text))
    text = re.sub(r"<https?://[^>]+>", "", text)
    text = re.sub(r"[`*_#>]+", "", text)
    return re.sub(r"\s+", " ", text).strip()
# ---------------------------------------------------------------------------
# Block parsing
# ---------------------------------------------------------------------------
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_BULLET_RE = re.compile(r"^[-*+]\s+(.*)$")
_NUMBER_RE = re.compile(r"^(\d+)[.)]\s+(.*)$")
_HR_RE = re.compile(r"^(?:-{3,}|\*{3,}|_{3,})$")
_TABLE_DELIM_RE = re.compile(r"^\|?[\s:\-|]+\|?$")


def _split_row(row: str) -> list[str]:
    """Split a pipe-table row, honouring escaped pipes."""
    row = row.strip()
    if row.startswith("|"):
        row = row[1:]
    if row.endswith("|"):
        row = row[:-1]
    return [cell.strip().replace("\\|", "|")
            for cell in re.split(r"(?<!\\)\|", row)]


def parse_blocks(markdown: str) -> tuple[list[tuple], dict]:
    """Parse the manuscript into blocks plus discovered front matter.

    Block kinds: ``("h", level, text)``, ``("p", text)``, ``("list", items)``,
    ``("table", header, rows)``, ``("code", text)``, ``("quote", text)``,
    ``("hr", None)``.
    """
    lines = str(markdown).replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.expandtabs(4) for line in lines.split("\n")]
    blocks: list[tuple] = []
    front: dict = {"title": None}
    index = 0
    total = len(lines)
    seen_title = False

    while index < total:
        line = lines[index]
        stripped = line.strip()

        if stripped.startswith("```"):
            language = stripped[3:].strip()
            index += 1
            buffer: list[str] = []
            while index < total and not lines[index].strip().startswith("```"):
                buffer.append(lines[index].rstrip())
                index += 1
            index += 1
            blocks.append(("code", "\n".join(buffer), language))
            continue

        if (stripped.startswith("|") and index + 1 < total
                and _TABLE_DELIM_RE.match(lines[index + 1].strip())):
            header = _split_row(stripped)
            rows: list[list[str]] = []
            index += 2
            while index < total and lines[index].strip().startswith("|"):
                rows.append(_split_row(lines[index].strip()))
                index += 1
            blocks.append(("table", header, rows))
            continue

        heading = _HEADING_RE.match(stripped)
        if heading:
            level = len(heading.group(1))
            text = heading.group(2).strip()
            if level == 1 and not seen_title and not blocks:
                front["title"] = strip_markdown(text)
                seen_title = True
            else:
                blocks.append(("h", level, text))
            index += 1
            continue

        if _HR_RE.match(stripped):
            blocks.append(("hr", None))
            index += 1
            continue

        if stripped.startswith(">"):
            quoted: list[str] = []
            while index < total and lines[index].strip().startswith(">"):
                quoted.append(lines[index].strip()[1:].strip())
                index += 1
            blocks.append(("quote", " ".join(q for q in quoted if q)))
            continue

        bullet = _BULLET_RE.match(stripped)
        number = _NUMBER_RE.match(stripped)
        if bullet or number:
            items: list[str] = []
            while index < total:
                candidate = lines[index].strip()
                bmatch = _BULLET_RE.match(candidate)
                nmatch = _NUMBER_RE.match(candidate)
                if bmatch:
                    items.append(bmatch.group(1).strip())
                elif nmatch:
                    items.append(nmatch.group(2).strip())
                elif not candidate:
                    break
                elif (candidate.startswith("|")
                      or candidate.startswith("```")
                      or candidate.startswith(">")
                      or _HEADING_RE.match(candidate)
                      or _HR_RE.match(candidate)):
                    break
                elif items:
                    items[-1] += " " + candidate      # wrapped bullet line
                else:
                    break
                index += 1
            blocks.append(("list", items, bool(number)))
            continue

        if not stripped:
            index += 1
            continue

        paragraph: list[str] = []
        while index < total:
            candidate = lines[index].strip()
            if not candidate:
                break
            if (candidate.startswith("|") or candidate.startswith("```")
                    or candidate.startswith(">")
                    or _HEADING_RE.match(candidate)
                    or _BULLET_RE.match(candidate)
                    or _NUMBER_RE.match(candidate)
                    or _HR_RE.match(candidate)):
                break
            paragraph.append(candidate)
            index += 1
        blocks.append(("p", " ".join(paragraph)))
    return blocks, front
# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------
_NUMERIC_RE = re.compile(r"^[~$€£]?[\d.,%+\-–—/ ]+$")


# Approximate width of one character in the 8.8pt table font, and the
# horizontal cell padding ReportLab adds on each side. Both are in POINTS:
# ``avail`` (the frame width) is in points, not centimetres.
_CHAR_PT = 4.8
_CELL_PAD_PT = 11.0


def _column_widths(header: Sequence[str], rows: Sequence[Sequence[str]],
                   avail: float) -> list[float]:
    count = len(header)
    if not count:
        return []
    longest = [0] * count
    longest_word = [1] * count
    for position in range(count):
        cells = [header[position]]
        cells += [row[position] for row in rows if position < len(row)]
        for cell in cells:
            plain = strip_markdown(cell)
            longest[position] = max(longest[position], len(plain))
            for word in plain.split():
                longest_word[position] = max(longest_word[position], len(word))
    weights = [max(6, min(52, value)) for value in longest]
    total = float(sum(weights)) or 1.0
    # A column must be wide enough for its longest unbreakable word, so short
    # headers such as "Source" or "Horizon" are never split mid-word.
    minimums = [min(avail / 2.0, _CHAR_PT * word + _CELL_PAD_PT)
                for word in longest_word]
    widths = [max(minimums[i], avail * weights[i] / total)
              for i in range(count)]
    overflow = sum(widths) - avail
    guard = 0
    while overflow > 0.01 and guard < count * 8:
        guard += 1
        slack = [widths[i] - minimums[i] for i in range(count)]
        widest = max(range(count), key=lambda index: slack[index])
        if slack[widest] <= 0:
            break
        reduce_by = min(overflow, slack[widest])
        widths[widest] -= reduce_by
        overflow -= reduce_by
    return widths


def build_table(header: Sequence[str], rows: Sequence[Sequence[str]],
                styles, avail: float):
    """Return a booktabs-style ``Table`` flowable for a Markdown table."""
    from reportlab.lib import colors
    from reportlab.platypus import Paragraph, Table, TableStyle

    count = len(header)
    body: list[list] = []
    head = [Paragraph(inline_markup(cell), styles["table_head"])
            for cell in list(header) + [""] * max(0, count - len(header))]
    body.append(head[:count])
    for row in rows:
        cells = list(row) + [""] * max(0, count - len(row))
        body.append([Paragraph(inline_markup(cell), styles["table"])
                     for cell in cells[:count]])

    widths = _column_widths(header, rows, avail)
    table = Table(body, colWidths=widths, repeatRows=1, hAlign="LEFT")
    rules = colors.HexColor("#4a5a6a")
    style = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3.2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3.2),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef2f7")),
        ("LINEABOVE", (0, 0), (-1, 0), 1.0, rules),
        ("LINEBELOW", (0, 0), (-1, 0), 0.6, rules),
        ("LINEBELOW", (0, -1), (-1, -1), 1.0, rules),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
         [colors.white, colors.HexColor("#f8fafc")]),
    ]
    for column in range(count):
        values = [row[column] for row in rows
                  if column < len(row) and str(row[column]).strip()]
        if values and all(_NUMERIC_RE.match(strip_markdown(v)) for v in values):
            style.append(("ALIGN", (column, 1), (column, -1), "RIGHT"))
    table.setStyle(TableStyle(style))
    return table


# ---------------------------------------------------------------------------
# Page furniture
# ---------------------------------------------------------------------------
class _NumberedCanvas:
    """Factory producing a canvas that stamps "Page X of Y" on every page."""

    @staticmethod
    def factory(footer):
        from reportlab.pdfgen import canvas as _canvas

        class NumberedCanvas(_canvas.Canvas):
            def __init__(self, *args, **kwargs):
                _canvas.Canvas.__init__(self, *args, **kwargs)
                self._states: list[dict] = []

            def showPage(self) -> None:
                self._states.append(dict(self.__dict__))
                self._startPage()

            def save(self) -> None:
                total = len(self._states)
                for state in self._states:
                    self.__dict__.update(state)
                    if footer:
                        footer(self, self._pageNumber, total)
                    _canvas.Canvas.showPage(self)
                _canvas.Canvas.save(self)

        return NumberedCanvas
# ---------------------------------------------------------------------------
# Story assembly
# ---------------------------------------------------------------------------
_ABSTRACT_TITLES = {"abstract", "executive summary"}
_REFERENCE_TITLES = {"references", "bibliography", "works cited",
                     "source register", "sources"}


def _callout(text: str, styles, avail: float):
    """Return a shaded, left-ruled callout box for a blockquote."""
    from reportlab.lib import colors
    from reportlab.platypus import Paragraph, Table, TableStyle

    box = Table([[Paragraph(inline_markup(text), styles["quote"])]],
                colWidths=[avail])
    box.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f4f6f8")),
        ("LINEBEFORE", (0, 0), (0, -1), 2.4, colors.HexColor("#0b3d6b")),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    return box


def _abstract_box(text: str, styles, avail: float):
    """Return the shaded abstract panel."""
    from reportlab.lib import colors
    from reportlab.platypus import Paragraph, Table, TableStyle

    box = Table(
        [[Paragraph("ABSTRACT", styles["abstract_label"])],
         [Paragraph(inline_markup(text), styles["abstract"])]],
        colWidths=[avail])
    box.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f6f8fa")),
        ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#c9d3dd")),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (-1, 0), 9),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 1),
        ("TOPPADDING", (0, 1), (-1, 1), 2),
        ("BOTTOMPADDING", (0, 1), (-1, 1), 11),
    ]))
    return box


def _code_block(text: str, styles):
    import textwrap

    from reportlab.platypus import Preformatted

    wrapped: list[str] = []
    for line in text.split("\n"):
        if len(line) <= 96:
            wrapped.append(line)
        else:
            wrapped.extend(textwrap.wrap(line, width=96,
                                         subsequent_indent="    "))
    return Preformatted("\n".join(wrapped), styles["code"])


_MM_NODE_RE = re.compile(r'([A-Za-z][\w]*)\s*\[\s*"([^"]*)"\s*\]')
_MM_EDGE_RE = re.compile(
    r'([A-Za-z][\w]*)\s*(?:-{2,}>|-\.\s*"[^"]*"\s*\.->|-\.->)\s*'
    r'(?:\|([^|]*)\|)?\s*([A-Za-z][\w]*)')


def _mermaid_flow(text: str, styles, avail: float) -> list:
    """Render a Mermaid flowchart as a readable vertical decision flow.

    Raw Mermaid syntax ("flowchart TD", ``A["x"] --> B["y"]``) is unreadable in
    a PDF, so nodes are drawn as boxes in first-seen order with labelled
    arrows, and any edge outside the linear chain (a consultation channel, for
    example) is listed underneath.
    """
    from reportlab.lib import colors
    from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

    labels: dict[str, str] = {}
    order: list[str] = []
    for match in _MM_NODE_RE.finditer(text):
        node, label = match.group(1), match.group(2)
        label = re.sub(r"<br\s*/?>", " · ", label).replace('"', "").strip()
        labels[node] = label
        if node not in order:
            order.append(node)

    stripped = _MM_NODE_RE.sub(lambda match: match.group(1), text)
    edges: list[tuple[str, str, str]] = []
    for match in _MM_EDGE_RE.finditer(stripped):
        src, label, dst = match.group(1), match.group(2), match.group(3)
        if src in labels and dst in labels and src != dst:
            edges.append((src, dst, (label or "").strip()))

    story: list = []
    # Topological order (stable by first appearance) so a consultation channel
    # is never drawn as if it followed the main chain.
    incoming = {node: 0 for node in order}
    for src, dst, _label in edges:
        incoming[dst] = incoming.get(dst, 0) + 1
    remaining = list(order)
    ordered: list[str] = []
    while remaining:
        ready = [node for node in remaining if incoming.get(node, 0) == 0]
        node = (ready or remaining)[0]
        ordered.append(node)
        remaining.remove(node)
        for src, dst, _label in edges:
            if src == node:
                incoming[dst] -= 1
    step = {node: index for index, node in enumerate(ordered, 1)}

    for number, node in enumerate(ordered, 1):
        box = Table([[Paragraph(inline_markup(f"{number}.  {labels[node]}"),
                                styles["table"])]], colWidths=[avail])
        box.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#eef2f7")),
            ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#8fa3b5")),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        story.append(box)

    if edges:
        relations = "; ".join(
            f"{step[src]} → {step[dst]}" + (f" ({label})" if label else "")
            for src, dst, label in edges[:10])
        story.append(Spacer(1, 2))
        story.append(Paragraph(
            f"<i>Relations:</i> {inline_markup(relations)}",
            styles["caption"]))
    return story
def build_story(blocks: Sequence[tuple], styles, *,
                avail: float,
                title: str | None = None,
                subtitle: str | None = None,
                meta_line: str | None = None,
                keywords: str | None = None) -> list:
    """Turn parsed blocks into a list of platypus flowables."""
    from reportlab.lib import colors
    from reportlab.platypus import (HRFlowable, KeepTogether, Paragraph,
                                    Spacer)

    story: list = []
    body_keywords = any(
        block[0] == "p" and strip_markdown(block[1]).lower().startswith(
            "keywords:") for block in blocks)
    if title:
        story.append(Paragraph(inline_markup(title), styles["title"]))
    if subtitle:
        story.append(Paragraph(inline_markup(subtitle), styles["subtitle"]))
    if meta_line:
        story.append(Paragraph(_esc(meta_line), styles["meta"]))
    if keywords and not body_keywords:
        story.append(Paragraph(
            f'<b>Keywords:</b> {inline_markup(keywords)}', styles["keywords"]))
    if title or meta_line or keywords:
        story.append(HRFlowable(width="100%", thickness=0.9,
                                color=colors.HexColor("#0b3d6b"),
                                spaceBefore=4, spaceAfter=12))

    in_references = False
    position = 0
    total = len(blocks)
    while position < total:
        block = blocks[position]
        kind = block[0]

        if kind == "h":
            _kind, level, text = block
            plain = strip_markdown(text).lower().rstrip(".:")
            in_references = plain in _REFERENCE_TITLES
            if plain in _ABSTRACT_TITLES:
                collected: list[str] = []
                cursor = position + 1
                while cursor < total and blocks[cursor][0] == "p":
                    collected.append(blocks[cursor][1])
                    cursor += 1
                if collected:
                    story.append(_abstract_box(" ".join(collected), styles,
                                               avail))
                    story.append(Spacer(1, 10))
                    position = cursor
                    continue
            key = {1: "h1", 2: "h2", 3: "h3"}.get(level, "h4")
            story.append(Paragraph(inline_markup(text), styles[key]))
            position += 1
            continue

        if kind == "p":
            text = block[1]
            if in_references:
                story.append(Paragraph(inline_markup(text),
                                       styles["reference"]))
            elif (text.startswith("Table ") or text.startswith("**Table")):
                story.append(Paragraph(inline_markup(text), styles["caption"]))
            else:
                story.append(Paragraph(inline_markup(text), styles["body"]))
            position += 1
            continue

        if kind == "list":
            items = block[1]
            ordered = bool(block[2]) if len(block) > 2 else False
            if in_references:
                for item in items:
                    story.append(Paragraph(inline_markup(item),
                                           styles["reference"]))
            else:
                for position_in_list, item in enumerate(items, 1):
                    if ordered:
                        story.append(Paragraph(
                            inline_markup(item), styles["numbered"],
                            bulletText=f"{position_in_list}."))
                    else:
                        story.append(Paragraph(
                            inline_markup(item), styles["bullet"],
                            bulletText="•"))
                story.append(Spacer(1, 3))
            position += 1
            continue

        if kind == "table":
            _kind, header, rows = block
            table = build_table(header, rows, styles, avail)
            story.append(Spacer(1, 3))
            story.append(KeepTogether([table]) if len(rows) <= 12 else table)
            story.append(Spacer(1, 9))
            position += 1
            continue

        if kind == "code":
            language = (block[2] if len(block) > 2 else "").lower()
            body_text = block[1]
            from .charts import CHART_KINDS, render_chart_block

            if language in CHART_KINDS:
                # A caption/note written just after the fence belongs to the
                # figure; consume it so it is typeset as a caption rather than
                # as a body paragraph.
                cursor = position + 1
                extras: list[str] = []
                while cursor < total and blocks[cursor][0] == "p":
                    text = blocks[cursor][1].strip()
                    if text.lower().startswith(("caption:", "note:",
                                                "title:", "benchmark:")):
                        extras.append(text)
                        cursor += 1
                    else:
                        break
                if extras:
                    body_text = body_text + "\n" + "\n".join(extras)
                story.extend(render_chart_block(language, body_text, styles,
                                                avail))
                position = cursor
                continue
            is_mermaid = (language in ("mermaid", "flow", "flowchart")
                          or body_text.lstrip().startswith(("flowchart",
                                                            "graph ")))
            story.append(Spacer(1, 3))
            if is_mermaid:
                story.extend(_mermaid_flow(body_text, styles, avail))
                story.append(Spacer(1, 9))
            else:
                story.append(_code_block(body_text, styles))
                story.append(Spacer(1, 8))
            position += 1
            continue

        if kind == "quote":
            text = block[1]
            plain = strip_markdown(text).lower()
            if text and not plain.startswith(("finalized research",
                                              "research paper",
                                              "draft research paper")):
                story.append(_callout(text, styles, avail))
                story.append(Spacer(1, 8))
            position += 1
            continue

        if kind == "hr":
            story.append(HRFlowable(width="100%", thickness=0.5,
                                    color=colors.HexColor("#c9d3dd"),
                                    spaceBefore=6, spaceAfter=6))
            position += 1
            continue

        position += 1
    return story
# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def render_manuscript(markdown: str, *, title: str | None = None,
                      subtitle: str | None = None,
                      meta_line: str | None = None,
                      keywords: str | None = None,
                      header_left: str | None = None,
                      header_right: str | None = None,
                      footer_left: str | None = None,
                      page_size=None) -> bytes:
    """Render a Markdown manuscript to research-paper-grade PDF bytes."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import cm
    from reportlab.platypus import (BaseDocTemplate, Frame, PageTemplate,
                                    Paragraph)

    fonts = register_fonts()
    styles = build_styles()
    blocks, front = parse_blocks(markdown)
    title_text = title or front.get("title") or "Research Paper"

    buffer = BytesIO()
    left = right = 2.15 * cm
    top = bottom = 2.35 * cm
    doc = BaseDocTemplate(
        buffer, pagesize=page_size or A4,
        leftMargin=left, rightMargin=right,
        topMargin=top, bottomMargin=bottom,
        title=strip_markdown(title_text),
        author=strip_markdown(meta_line or "") or "None-Bias Research Agent",
        creator="Credential Research Toolkit",
        subject="Finalized research paper",
    )
    story = build_story(blocks, styles, avail=doc.width, title=title_text,
                        subtitle=subtitle, meta_line=meta_line,
                        keywords=keywords)
    if not blocks:
        story.append(Paragraph("(No content.)", styles["body"]))

    rule = colors.HexColor("#9fb0c0")
    muted = colors.HexColor("#555555")
    width, height = doc.pagesize

    def draw_header(canvas, _doc) -> None:
        if canvas.getPageNumber() == 1:      # title page carries no running head
            return
        canvas.saveState()
        canvas.setStrokeColor(rule)
        canvas.setLineWidth(0.6)
        canvas.line(left, height - top + 0.5 * cm,
                    width - right, height - top + 0.5 * cm)
        canvas.setFont(fonts.sans, 7.4)
        canvas.setFillColor(muted)
        canvas.drawString(left, height - top + 0.72 * cm,
                          _header_text(header_left or title_text)[:110])
        canvas.drawRightString(width - right, height - top + 0.72 * cm,
                               header_right or "RESEARCH PAPER")
        canvas.restoreState()

    def draw_footer(canvas, page: int, total: int) -> None:
        canvas.saveState()
        canvas.setStrokeColor(rule)
        canvas.setLineWidth(0.5)
        canvas.line(left, bottom - 0.55 * cm, width - right,
                    bottom - 0.55 * cm)
        canvas.setFont(fonts.sans, 7.4)
        canvas.setFillColor(muted)
        canvas.drawString(left, bottom - 1.02 * cm,
                          _header_text(footer_left or "")[:110])
        canvas.drawRightString(width - right, bottom - 1.02 * cm,
                               f"Page {page} of {total}")
        canvas.restoreState()

    frame = Frame(left, bottom, doc.width, doc.height, id="body",
                  leftPadding=0, rightPadding=0, topPadding=0,
                  bottomPadding=0)
    doc.addPageTemplates([PageTemplate(id="manuscript", frames=[frame],
                                       onPage=draw_header)])
    doc.build(story,
              canvasmaker=_NumberedCanvas.factory(draw_footer))
    return buffer.getvalue()


def write_manuscript_pdf(markdown: str, path: str | Path, **kwargs) -> Path:
    """Render *markdown* into *path* (creating parent folders)."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(render_manuscript(markdown, **kwargs))
    return destination


def render_paper_pdf(markdown: str, meta) -> bytes:
    """Render a finalized paper (``PaperMeta``) to PDF bytes.

    ``meta`` is duck-typed: any object with ``title``, ``author``,
    ``created_at``, ``paper_id``, ``topic``, ``status``, ``target_kind``,
    ``findings``, ``sources`` and ``tags`` works.
    """
    tags = ", ".join(getattr(meta, "tags", []) or [])
    kind = str(getattr(meta, "target_kind", "") or "").strip()
    status = str(getattr(meta, "status", "final") or "final").upper()
    subtitle = (f"{kind.replace('-', ' ').title()} · {status} · "
                f"Topic: {getattr(meta, 'topic', '')}") if kind else None
    meta_line = (
        f"{getattr(meta, 'author', '')}  ·  "
        f"Published {getattr(meta, 'created_at', '')}"
        f"  ·  Paper ID {getattr(meta, 'paper_id', '')}"
        f"  ·  Findings {getattr(meta, 'findings', 0)}"
        f"  ·  Sources {getattr(meta, 'sources', 0)}")
    return render_manuscript(
        markdown,
        title=getattr(meta, "title", None),
        subtitle=subtitle,
        meta_line=meta_line,
        keywords=tags or None,
        header_left=getattr(meta, "title", None),
        footer_left=f"{getattr(meta, 'topic', '')}/"
                    f"{getattr(meta, 'paper_id', '')}",
    )


__all__ = ["register_fonts", "build_styles", "inline_markup",
           "strip_markdown", "parse_blocks", "build_table", "build_story",
           "render_manuscript", "write_manuscript_pdf", "render_paper_pdf",
           "FontSet"]