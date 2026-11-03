"""Render a public GitHub contribution calendar with fixed shade thresholds."""

from __future__ import annotations

import argparse
import html
import json
import re
from datetime import date, timedelta
from html.parser import HTMLParser
from pathlib import Path
from urllib.request import Request, urlopen


USERNAME = "bahimehdi"
THRESHOLDS = (1, 3, 6, 10)
COLORS = ("#1B2B26", "#1F5C42", "#27875B", "#36B875", "#78E5A5")
CELL = 10
GAP = 3
LEFT = 34
TOP = 38


class CalendarParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.cells: dict[str, tuple[str, str]] = {}
        self.tooltips: dict[str, str] = {}
        self.tooltip_for: str | None = None
        self.tooltip_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "td" and "ContributionCalendar-day" in (attributes.get("class") or ""):
            cell_id = attributes.get("id")
            day = attributes.get("data-date")
            if cell_id and day:
                self.cells[cell_id] = (day, attributes.get("data-level") or "")
        elif tag == "tool-tip":
            self.tooltip_for = attributes.get("for")
            self.tooltip_text = []

    def handle_data(self, data: str) -> None:
        if self.tooltip_for is not None:
            self.tooltip_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "tool-tip" and self.tooltip_for is not None:
            self.tooltips[self.tooltip_for] = "".join(self.tooltip_text).strip()
            self.tooltip_for = None
            self.tooltip_text = []


def parse_calendar(source: str) -> dict[date, int]:
    parser = CalendarParser()
    parser.feed(source)
    days: dict[date, int] = {}
    for cell_id, (raw_day, _) in parser.cells.items():
        day = date.fromisoformat(raw_day)
        tooltip = parser.tooltips.get(cell_id, "")
        if tooltip.startswith("No contributions"):
            count = 0
        else:
            match = re.match(r"^([\d,]+) contributions?\b", tooltip)
            if not match:
                raise ValueError(f"Cannot read contribution count for {day}: {tooltip!r}")
            count = int(match.group(1).replace(",", ""))
        if day in days:
            raise ValueError(f"Duplicate contribution day: {day}")
        days[day] = count
    if not 350 <= len(days) <= 372:
        raise ValueError(f"Unexpected calendar length: {len(days)} days")
    first, last = min(days), max(days)
    if (last - first).days + 1 != len(days):
        raise ValueError("Contribution calendar is missing dates")
    return days


def shade(count: int) -> int:
    return sum(count >= threshold for threshold in THRESHOLDS)


def render_svg(days: dict[date, int]) -> str:
    first, last = min(days), max(days)
    first_sunday = first - timedelta(days=(first.weekday() + 1) % 7)
    weeks = (last - first_sunday).days // 7 + 1
    width = LEFT + weeks * (CELL + GAP) + 18
    height = 172
    total = sum(days.values())
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">',
        f'<title id="title">{total} contributions in the last year</title>',
        '<desc id="desc">Daily GitHub contributions for bahimehdi. Shades represent 0, 1 to 2, 3 to 5, 6 to 9, and 10 or more contributions.</desc>',
        f'<rect width="{width}" height="{height}" rx="12" fill="#0D1117"/>',
        f'<text x="{LEFT}" y="22" fill="#F0F6FC" font-family="Arial, sans-serif" font-size="13" font-weight="600">{total} contributions in the last year</text>',
    ]
    for month in (first_sunday + timedelta(days=i) for i in range((last - first_sunday).days + 1)):
        if month.day != 1:
            continue
        x = LEFT + ((month - first_sunday).days // 7) * (CELL + GAP)
        lines.append(f'<text x="{x}" y="34" fill="#AABDB3" font-family="Arial, sans-serif" font-size="10">{month:%b}</text>')
    for weekday, label in ((1, "Mon"), (3, "Wed"), (5, "Fri")):
        y = TOP + weekday * (CELL + GAP) + 9
        lines.append(f'<text x="8" y="{y}" fill="#AABDB3" font-family="Arial, sans-serif" font-size="9">{label}</text>')
    for day, count in sorted(days.items()):
        week = (day - first_sunday).days // 7
        weekday = (day.weekday() + 1) % 7
        x = LEFT + week * (CELL + GAP)
        y = TOP + weekday * (CELL + GAP)
        label = html.escape(f"{day.isoformat()}: {count} contribution{'s' if count != 1 else ''}")
        lines.append(f'<rect x="{x}" y="{y}" width="{CELL}" height="{CELL}" rx="2" fill="{COLORS[shade(count)]}"><title>{label}</title></rect>')
    legend_y = 147
    lines.append(f'<text x="{LEFT}" y="{legend_y}" fill="#AABDB3" font-family="Arial, sans-serif" font-size="10">Daily contributions</text>')
    for i, label in enumerate(("0", "1–2", "3–5", "6–9", "10+")):
        x = LEFT + 112 + i * 80
        lines.append(f'<rect x="{x}" y="{legend_y - 9}" width="10" height="10" rx="2" fill="{COLORS[i]}"/>')
        lines.append(f'<text x="{x + 15}" y="{legend_y}" fill="#AABDB3" font-family="Arial, sans-serif" font-size="10">{label}</text>')
    lines.append('</svg>')
    return "\n".join(lines) + "\n"


def main() -> None:
    cli = argparse.ArgumentParser()
    cli.add_argument("--json", type=Path, help="Use a local JSON fixture instead of fetching GitHub")
    cli.add_argument("--output", type=Path, default=Path("assets/contributions.svg"))
    args = cli.parse_args()
    if args.json:
        items = json.loads(args.json.read_text(encoding="utf-8"))
        days = {date.fromisoformat(item["date"]): int(item["count"]) for item in items}
        if not 350 <= len(days) <= 372:
            raise ValueError(f"Unexpected calendar length: {len(days)} days")
    else:
        request = Request(
            f"https://github.com/users/{USERNAME}/contributions",
            headers={"User-Agent": "bahimehdi-profile-calendar/1.0", "Accept": "text/html"},
        )
        with urlopen(request, timeout=20) as response:
            source = response.read().decode("utf-8")
        days = parse_calendar(source)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render_svg(days), encoding="utf-8")


if __name__ == "__main__":
    main()
