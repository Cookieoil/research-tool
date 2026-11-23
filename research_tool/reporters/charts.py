"""Charts and visual panels for research papers (reportlab graphics only).

A paper that shows only prose and pipe tables is harder to read than it needs
to be. This module renders compact, print-quality visuals:

* ``bar_chart``   - ranked horizontal bars with a value at every bar end;
* ``line_chart``  - annotated trend lines (markers plus value labels);
* ``stat_panel``  - a strip of headline-figure cards;
* ``heatmap``     - a shaded intensity matrix plus a colour-scale legend;
* ``timeline``    - dated milestones on a node-and-spine rail.

Figures are drawn as custom vector primitives rather than with reportlab's
default chart widgets. That choice fixes what those widgets do inside a
document: rotated category labels clipping off the bottom of the figure,
overlapping labels, plots with no data labels, and axis furniture that fights
the page. Every figure measures its own text with ``pdfmetrics.stringWidth``,
sizes itself to its content, and uses publication styling (light dashed
gridlines, one accent per series, direct labels, no redundant box).
"""

from __future__ import annotations

import math
import re
from typing import Sequence

from reportlab.graphics.shapes import Drawing, Line, Rect, String
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.platypus import KeepTogether, Paragraph, Spacer, Table, TableStyle

from .academic_pdf import inline_markup, register_fonts, strip_markdown

INK = colors.HexColor("#1a1a1a")
ACCENT = colors.HexColor("#0b3d6b")
MUTED = colors.HexColor("#555555")
FAINT = colors.HexColor("#8a97a3")
GRID = colors.HexColor("#dde3e9")
RULE = colors.HexColor("#9fb0c0")
BENCHMARK = colors.HexColor("#b06a00")
SERIES_COLORS = (ACCENT, BENCHMARK, colors.HexColor("#2f7d5d"),
                 colors.HexColor("#8a3b5c"))

_NUMBER = re.compile(r"^-?\d+(?:[.,]\d+)?%?$")


def to_number(value: str) -> float | None:
    """Return *value* as a float, or ``None`` when it is not numeric."""
    text = str(value).strip().replace("\u2212", "-")
    if not _NUMBER.match(text):
        return None
    return float(text.rstrip("%").replace(",", ""))


def _text_width(text: str, font: str, size: float) -> float:
    """Measure *text* in points (the unit all figure geometry uses)."""
    from reportlab.pdfbase import pdfmetrics

    return pdfmetrics.stringWidth(str(text), font, size)


def _wrap(text: str, font: str, size: float, max_width: float,
          max_lines: int = 2) -> list[str]:
    """Greedy word-wrap *text* into at most *max_lines* lines."""
    words = str(text).split()
    lines: list[str] = []
    current = ""
    used = 0
    for word in words:
        candidate = f"{current} {word}".strip()
        if current and _text_width(candidate, font, size) > max_width:
            if len(lines) == max_lines - 1:
                break
            lines.append(current)
            used += len(current.split())
            current = word
        else:
            current = candidate
    if current and len(lines) < max_lines:
        lines.append(current)
        used += len(current.split())
    if used < len(words) and lines:                    # ellipsise the overflow
        last = lines[-1]
        while last and _text_width(last + "…", font, size) > max_width:
            last = last[:-1]
        lines[-1] = last + "…"
    return lines or [""]


_AXIS_STEPS = (0.5, 1, 2, 2.5, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000,
               2000, 5000)


def _axis(value: float, min_ticks: int = 3, max_ticks: int = 6
          ) -> tuple[float, list[float]]:
    """Return a friendly axis maximum and its ticks for *value*.

    Picks the step that keeps the axis to three to six round ticks with the
    least headroom, so a 45 percent maximum becomes 0/10/20/30/40/50 rather
    than 0/18.75/37.5/56.25/75.
    """
    if value <= 0:
        return 1.0, [0.0, 0.25, 0.5, 0.75, 1.0]
    best: tuple[float, int, float, float] | None = None
    for step in _AXIS_STEPS:
        top = step * math.ceil(value / step - 1e-9)
        ticks = int(round(top / step))
        if not (min_ticks <= ticks <= max_ticks):
            continue
        headroom = top / value
        if best is None or headroom < best[0] - 1e-9 or (
                abs(headroom - best[0]) < 1e-9 and ticks > best[1]):
            best = (headroom, ticks, step, top)
    if best is None:
        step = _AXIS_STEPS[-1]
        top = step * math.ceil(value / step)
    else:
        _headroom, _ticks_count, step, top = best
    count = int(round(top / step))
    return float(top), [step * index for index in range(count + 1)]


def _fmt(value: float) -> str:
    return f"{value:g}"


def parse_chart_block(text: str, *, has_header: bool = True
                      ) -> tuple[dict, list[str], list[list[str]]]:
    """Parse a chart fence: ``key: value`` options, then a pipe table.

    Options may appear before or after the table, because ``caption:`` reads
    more naturally at the end of the block. ``has_header=False`` keeps every
    table row as data, for the KPI panel and the timeline whose first row is
    content rather than column names.
    """
    options: dict[str, str] = {}
    header: list[str] = []
    rows: list[list[str]] = []
    for line in str(text).split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        if not stripped.startswith("|"):
            if ":" in stripped:
                key, value = stripped.split(":", 1)
                key = key.strip().lower()
                if not rows or key in ("caption", "note", "title",
                                       "benchmark", "suffix", "invert"):
                    options[key] = value.strip()
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if all(set(cell) <= set("-: ") for cell in cells):     # delimiter row
            continue
        if has_header and not header:
            header = cells
            continue
        if not has_header and not header:
            header = [f"Col {index + 1}" for index in range(len(cells))]
        rows.append(cells)
    return options, header, rows
def _extract_series(header: Sequence[str], rows: Sequence[Sequence[str]],
                    limit: int = 3) -> tuple[list[str], list[list[float]],
                                             list[str]]:
    """Split a chart table into row labels, numeric series and series names."""
    labels = [strip_markdown(str(row[0])) if row else "" for row in rows]
    series: list[list[float]] = []
    names: list[str] = []
    for column in range(1, min(limit + 1, len(header))):
        values: list[float] = []
        for row in rows:
            number = to_number(row[column]) if column < len(row) else None
            if number is None:
                break
            values.append(number)
        if len(values) == len(rows) and values:
            series.append(values)
            names.append(str(header[column]))
    return labels, series, names


def bar_chart(header: Sequence[str], rows: Sequence[Sequence[str]], *,
              width: float, title: str | None = None,
              benchmark: float | None = None, suffix: str = "") -> Drawing | None:
    """Ranked horizontal bars: readable labels, values at the bar ends.

    Horizontal orientation is deliberate. Categorical research data usually has
    multi-word labels ("Promotion incentives expand", "Foreign firms' share of
    exports"); rotating them under vertical bars is what makes such charts
    cluttered and clipped.
    """
    fonts = register_fonts()
    labels, series, names = _extract_series(header, rows)
    if not series or not labels:
        return None

    label_font, label_size = fonts.sans, 6.9
    value_font, value_size = fonts.sans, 6.6
    axis_font, axis_size = fonts.sans, 6.0

    label_width = min(width * 0.46,
                      max(_text_width(label, label_font, label_size)
                          for label in labels) + 7)
    value_gutter = max(_text_width("150%", value_font, value_size) + 6, 22)
    plot_x = label_width + 5
    plot_width = max(40.0, width - plot_x - value_gutter)

    highest = max(max(values) for values in series)
    if benchmark is not None:
        highest = max(highest, benchmark)
    axis_max, axis_ticks = _axis(highest)
    grouped = len(series) > 1
    bar_height = 6.0 if grouped else 8.0
    row_height = (len(series) * bar_height + 4.0) if grouped else 12.5
    top_pad = 15 if title else 3
    bottom_pad = 15
    height = top_pad + row_height * len(labels) + bottom_pad

    drawing = Drawing(width, height)
    plot_top = height - top_pad
    plot_bottom = bottom_pad

    for tick in axis_ticks:                       # dashed vertical gridlines
        x = plot_x + plot_width * (tick / axis_max)
        drawing.add(Line(x, plot_bottom, x, plot_top, strokeColor=GRID,
                         strokeWidth=0.5, strokeDashArray=[1.5, 2.5]))
        drawing.add(String(x, plot_bottom - 8, _fmt(tick), fontName=axis_font,
                           fontSize=axis_size, fillColor=FAINT,
                           textAnchor="middle"))
    drawing.add(Line(plot_x, plot_bottom, plot_x, plot_top, strokeColor=RULE,
                     strokeWidth=0.7))

    if benchmark is not None:                     # reference line
        x = plot_x + plot_width * (benchmark / axis_max)
        drawing.add(Line(x, plot_bottom, x, plot_top, strokeColor=BENCHMARK,
                         strokeWidth=0.9, strokeDashArray=[3, 2]))
        drawing.add(String(x, plot_top + 2, f"baseline {_fmt(benchmark)}"
                           f"{suffix}", fontName=axis_font, fontSize=axis_size,
                           fillColor=BENCHMARK, textAnchor="middle"))

    for row_index, label in enumerate(labels):
        row_top = plot_top - row_index * row_height
        wrapped = _wrap(label, label_font, label_size, label_width - 6)
        for line_index, line in enumerate(wrapped):
            drawing.add(String(label_width - 2,
                               row_top - 9 - line_index * 7.6, line,
                               fontName=label_font, fontSize=label_size,
                               fillColor=INK, textAnchor="end"))
        for series_index, values in enumerate(series):
            value = values[row_index]
            bar_width = plot_width * (value / axis_max) if axis_max else 0
            if grouped:
                y = row_top - (series_index + 1) * bar_height - 2
                bar_h = bar_height - 1.6
            else:
                y = row_top - 10.5
                bar_h = bar_height
            colour = SERIES_COLORS[series_index % len(SERIES_COLORS)]
            drawing.add(Rect(plot_x, y, bar_width, bar_h, fillColor=colour,
                             strokeColor=None))
            drawing.add(String(plot_x + bar_width + 3, y + 1,
                               f"{_fmt(value)}{suffix}", fontName=value_font,
                               fontSize=value_size, fillColor=INK))

    if title:
        drawing.add(String(0, height - 8, title, fontName=fonts.sans,
                           fontSize=8.2, fillColor=ACCENT))
    if grouped:
        x = width
        for index in reversed(range(len(series))):
            text = names[index]
            chip = _text_width(text, axis_font, axis_size) + 12
            x -= chip
            drawing.add(Rect(x, height - 9, 6, 6, strokeColor=None,
                             fillColor=SERIES_COLORS[index
                                                     % len(SERIES_COLORS)]))
            drawing.add(String(x + 9, height - 9, text, fontName=axis_font,
                               fontSize=axis_size, fillColor=MUTED))
    return drawing
def line_chart(header: Sequence[str], rows: Sequence[Sequence[str]], *,
               width: float, title: str | None = None, invert: bool = False,
               suffix: str = "") -> Drawing | None:
    """Annotated trend lines: markers, direct value labels and a legend.

    ``invert=True`` plots larger values lower, which is what a "lower is
    better" series needs: a grossing-rank series that worsens from 78 to 153
    then slopes downwards, matching how a reader reads a decline.
    """
    fonts = register_fonts()
    labels, series, names = _extract_series(header, rows, limit=2)
    if not series or not labels:
        return None

    axis_font, axis_size = fonts.sans, 6.0
    value_font, value_size = fonts.sans, 6.4
    label_font, label_size = fonts.sans, 6.4

    top_pad = 26 if title or len(series) > 1 else 10
    plot_height = 62.0
    bottom_pad = 20
    height = top_pad + plot_height + bottom_pad
    left_pad = 24.0
    right_pad = 12.0
    plot_x = left_pad
    plot_width = max(40.0, width - left_pad - right_pad)
    plot_top = height - top_pad
    plot_bottom = bottom_pad

    flat = [value for values in series for value in values]
    axis_min = 0.0 if min(flat) >= 0 and max(flat) > 4 * abs(min(flat)) else \
        max(0.0, min(flat) * 0.9)
    axis_max, axis_ticks = _axis(max(flat) * 1.02)

    def point_x(index: int) -> float:
        if len(labels) == 1:
            return plot_x + plot_width / 2
        return plot_x + plot_width * index / (len(labels) - 1)

    def point_y(value: float) -> float:
        span = (axis_max - axis_min) or 1.0
        fraction = (value - axis_min) / span
        if invert:
            fraction = 1.0 - fraction
        return plot_bottom + plot_height * fraction

    drawing = Drawing(width, height)
    for tick in axis_ticks:
        y = point_y(tick)
        drawing.add(Line(plot_x, y, plot_x + plot_width, y, strokeColor=GRID,
                         strokeWidth=0.5, strokeDashArray=[1.5, 2.5]))
        drawing.add(String(plot_x - 4, y - 2, _fmt(tick), fontName=axis_font,
                           fontSize=axis_size, fillColor=FAINT,
                           textAnchor="end"))
    drawing.add(Line(plot_x, plot_bottom, plot_x + plot_width, plot_bottom,
                     strokeColor=RULE, strokeWidth=0.7))

    for index, label in enumerate(labels):        # x-axis category labels
        text = str(label)
        if _text_width(text, label_font, label_size) > plot_width / max(
                len(labels) - 1, 1) + 6:
            text = _wrap(text, label_font, label_size,
                         plot_width / max(len(labels) - 1, 1) + 6, 1)[0]
        drawing.add(String(point_x(index), plot_bottom - 9, text,
                           fontName=label_font, fontSize=label_size,
                           fillColor=MUTED, textAnchor="middle"))

    for series_index, values in enumerate(series):
        colour = SERIES_COLORS[series_index % len(SERIES_COLORS)]
        points = [(point_x(index), point_y(value))
                  for index, value in enumerate(values)]
        for start, end in zip(points, points[1:]):
            drawing.add(Line(start[0], start[1], end[0], end[1],
                             strokeColor=colour, strokeWidth=1.7))
        for (x, y), value in zip(points, values):
            drawing.add(Line(x - 2.6, y, x + 2.6, y, strokeColor=colors.white,
                             strokeWidth=2.4))          # halo under the dot
            drawing.add(Line(x, y - 2.6, x, y + 2.6, strokeColor=colors.white,
                             strokeWidth=2.4))
            drawing.add(Line(x - 2.3, y, x + 2.3, y, strokeColor=colour,
                             strokeWidth=1.6))
            drawing.add(Line(x, y - 2.3, x, y + 2.3, strokeColor=colour,
                             strokeWidth=1.6))
            drawing.add(String(x, y + 4.4, f"{_fmt(value)}{suffix}",
                               fontName=value_font, fontSize=value_size,
                               fillColor=colour, textAnchor="middle"))

    if title:
        drawing.add(String(0, height - 8, title, fontName=fonts.sans,
                           fontSize=8.2, fillColor=ACCENT))
    if len(series) > 1:
        x = width
        for index in reversed(range(len(series))):
            text = names[index]
            chip = _text_width(text, axis_font, axis_size) + 14
            x -= chip
            drawing.add(Line(x + 3, height - 6, x + 11, height - 6,
                             strokeColor=SERIES_COLORS[index
                                                       % len(SERIES_COLORS)],
                             strokeWidth=1.7))
            drawing.add(String(x + 14, height - 8, text, fontName=axis_font,
                               fontSize=axis_size, fillColor=MUTED))
    return drawing
def _escape(value: object) -> str:
    """Escape a figure value for a ReportLab paragraph."""
    return (str(value).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))


def stat_panel(rows: Sequence[Sequence[str]], styles, *, avail: float,
               columns: int = 4):
    """A strip of headline-figure cards: big value over a small label."""
    from reportlab.lib.styles import ParagraphStyle

    items = [(str(row[0]), str(row[1]) if len(row) > 1 else "")
             for row in rows if row and str(row[0]).strip()]
    if not items:
        return None
    font = register_fonts().sans
    value_style = ParagraphStyle("RStatValue", parent=styles["table"],
                                 fontName=font, fontSize=13, leading=15,
                                 alignment=1, textColor=ACCENT, spaceAfter=2)
    label_style = ParagraphStyle("RStatLabel", parent=styles["caption"],
                                 fontName=font, fontSize=7.1, leading=8.8,
                                 alignment=1, textColor=MUTED)

    cells: list[list] = []
    row: list = []
    for value, label in items:
        row.append([Paragraph(f"<b>{_escape(value)}</b>", value_style),
                    Paragraph(_escape(label), label_style)])
        if len(row) == columns:
            cells.append(row)
            row = []
    if row:
        while len(row) < columns:
            row.append("")
        cells.append(row)

    grid = Table(cells, colWidths=[avail / columns] * columns, hAlign="LEFT")
    grid.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f4f7fa")),
        ("LINEABOVE", (0, 0), (-1, 0), 2.0, ACCENT),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#ccd7e1")),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#e2e9ef")),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))
    return grid


def _shade(fraction: float) -> colors.Color:
    """Blend white towards the accent colour for a 0..1 intensity."""
    fraction = max(0.0, min(1.0, fraction))
    return colors.Color(
        1 - (1 - ACCENT.red) * fraction,
        1 - (1 - ACCENT.green) * fraction,
        1 - (1 - ACCENT.blue) * fraction)


def heatmap(header: Sequence[str], rows: Sequence[Sequence[str]], styles, *,
            avail: float, scale_max: float | None = None):
    """Shaded intensity matrix with a colour-scale legend under the table."""
    from reportlab.lib.styles import ParagraphStyle

    fonts = register_fonts()
    first, *series = header
    body: list[list] = [[Paragraph(f"<b>{first}</b>", styles["table_head"])]]
    body[0] += [Paragraph(f"<b>{name}</b>", styles["table_head"])
                for name in series]

    numbers: list[list[float]] = []
    for row in rows:
        values = [to_number(row[index + 1]) if index + 1 < len(row) else None
                  for index in range(len(series))]
        numbers.append([0.0 if value is None else value for value in values])
    scale = scale_max or max((max(row) for row in numbers if row), default=1.0)

    label_width = min(
        avail * 0.36,
        max([_text_width(first, fonts.sans, 8.6)]
            + [_text_width(str(row[0]), fonts.body, 8.8)
               for row in rows if row]) + 12)
    cell_width = max(20.0, (avail - label_width) / max(1, len(series)))

    style = [
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef2f7")),
        ("LINEABOVE", (0, 0), (-1, 0), 1.0, colors.HexColor("#4a5a6a")),
        ("LINEBELOW", (0, 0), (-1, 0), 0.6, colors.HexColor("#4a5a6a")),
        ("LINEBELOW", (0, len(rows)), (-1, len(rows)), 1.0,
         colors.HexColor("#4a5a6a")),
        ("TOPPADDING", (0, 0), (-1, -1), 3.6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3.6),
        ("ALIGN", (1, 1), (-1, -1), "CENTER"),
    ]
    for row_index, row in enumerate(rows):
        cells: list = [Paragraph(_escape(row[0]) if row else "",
                                 styles["table"])]
        for column_index, value in enumerate(numbers[row_index]):
            fraction = value / scale if scale else 0.0
            text_style = ParagraphStyle(
                f"RCell{row_index}_{column_index}", parent=styles["table"],
                fontName=fonts.sans, alignment=1,
                textColor=colors.white if fraction > 0.55 else INK)
            cells.append(Paragraph(f"{value:g}", text_style))
            style.append(("BACKGROUND", (column_index + 1, row_index + 1),
                          (column_index + 1, row_index + 1), _shade(fraction)))
        body.append(cells)

    legend_row: list = [Paragraph("<i>Scale</i>", styles["caption"])]
    for step in range(max(1, len(series))):
        fraction = step / max(1, len(series) - 1)
        legend_row.append(Paragraph(f"{round(fraction * scale):g}",
                                    styles["caption"]))
        style.append(("BACKGROUND", (step + 1, len(rows) + 1),
                      (step + 1, len(rows) + 1), _shade(fraction)))
    body.append(legend_row)

    table = Table(body, colWidths=[label_width] + [cell_width] * len(series),
                  hAlign="LEFT", repeatRows=1)
    table.setStyle(TableStyle(style))
    return table
def timeline(rows: Sequence[Sequence[str]], styles, *, avail: float):
    """Dated milestones: a node rail with the date left and the event right."""
    if not rows:
        return None
    fonts = register_fonts()
    date_style = styles["caption"]
    node_style = styles["caption"].clone("RNode")
    node_style.alignment = 1
    body: list[list] = []
    for row in rows:
        date = str(row[0]) if row else ""
        event = str(row[1]) if len(row) > 1 else ""
        body.append([Paragraph(f"<b>{_escape(date)}</b>", date_style),
                     Paragraph("●", node_style),
                     Paragraph(_escape(event), styles["table"])])
    date_column = min(avail * 0.22,
                      max(_text_width(str(row[0]), fonts.sans, 7.4)
                          for row in rows if row) + 8)
    table = Table(body, colWidths=[date_column, 12, avail - date_column - 12],
                  hAlign="LEFT")
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (0, 0), (0, -1), "RIGHT"),
        ("TEXTCOLOR", (1, 0), (1, -1), ACCENT),
        ("LINEBEFORE", (1, 0), (1, -1), 1.2, colors.HexColor("#c3cfda")),
        ("LEFTPADDING", (0, 0), (0, -1), 2),
        ("RIGHTPADDING", (0, 0), (0, -1), 5),
        ("LEFTPADDING", (1, 0), (1, -1), 1),
        ("RIGHTPADDING", (1, 0), (1, -1), 4),
        ("LEFTPADDING", (2, 0), (2, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 3.4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3.4),
        ("ROWBACKGROUNDS", (0, 0), (-1, -1),
         [colors.white, colors.HexColor("#f8fafc")]),
    ]))
    return table


CHART_KINDS = ("chart-bars", "chart-line", "chart-stats", "chart-heatmap",
               "chart-timeline")


def render_chart_block(kind: str, text: str, styles, avail: float) -> list:
    """Turn a chart fence into one unbreakable figure (visual + caption).

    The title, note and caption travel with the drawing inside a
    ``KeepTogether`` so a page break can never orphan a figure title or a
    caption from its chart.
    """
    from reportlab.lib.styles import ParagraphStyle

    has_header = kind not in ("chart-stats", "chart-timeline")
    options, header, rows = parse_chart_block(text, has_header=has_header)
    title = options.get("title")
    caption = options.get("caption")
    note = options.get("note")
    suffix = options.get("suffix", "")
    invert = str(options.get("invert", "")).strip().lower() in ("true", "1",
                                                               "yes", "on")
    benchmark = to_number(options["benchmark"]) if options.get("benchmark") \
        else None

    visual = None
    if kind == "chart-stats":
        visual = stat_panel(rows, styles, avail=avail,
                            columns=int(options.get("columns", 4) or 4))
    elif kind == "chart-heatmap":
        visual = heatmap(header, rows, styles, avail=avail,
                         scale_max=to_number(options["scale"]) if
                         options.get("scale") else None)
    elif kind == "chart-timeline":
        visual = timeline(rows, styles, avail=avail)
    elif kind == "chart-line":
        visual = line_chart(header, rows, width=avail, title=title,
                            invert=invert, suffix=suffix)
    else:
        visual = bar_chart(header, rows, width=avail, title=title,
                           benchmark=benchmark, suffix=suffix)
    if visual is None:
        return []

    figure: list = []
    if title and kind in ("chart-stats", "chart-heatmap", "chart-timeline"):
        figure.append(Paragraph(
            f"<b>{inline_markup(title)}</b>",
            ParagraphStyle("RChartTitle", parent=styles["caption"],
                           fontName=register_fonts().sans, fontSize=8.2,
                           textColor=ACCENT)))
        figure.append(Spacer(1, 3))
    figure.append(visual)
    if note:
        figure.append(Spacer(1, 3))
        figure.append(Paragraph(f"<i>{inline_markup(note)}</i>",
                                styles["caption"]))
    if caption:
        figure.append(Spacer(1, 2.5))
        figure.append(Paragraph(inline_markup(caption), styles["caption"]))
    return [Spacer(1, 5), KeepTogether(figure), Spacer(1, 9)]


__all__ = ["CHART_KINDS", "render_chart_block", "parse_chart_block",
           "bar_chart", "line_chart", "stat_panel", "heatmap", "timeline",
           "to_number"]
