#!/usr/bin/env python3
"""Validate and plot reviewed transmitter-event evidence, never inferred RF spans.

The event-only schema deliberately refuses continuous on/off or allocation-null
intervals. Calendar record dates have no invented UTC conversion. Imports do
not download anything; plotting imports matplotlib only when requested.
"""
from __future__ import annotations

import argparse
from datetime import date
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import textwrap
import xml.etree.ElementTree as ET
import zipfile

SCHEMA = "dtv-transmitter-history-v1"
KINDS = {"operator_on_month", "operator_shutdown_month", "ised_date_field",
         "administrative", "filing_receipt"}
MONTH_KINDS = {"operator_on_month", "operator_shutdown_month"}
HEADER = ("Call sign", "New DTV channel", "Existing channel", "Type", "Province",
          "City", "Phase number", "Start of on-air testing period (MM/DD/YYYY)",
          "End of on-air testing period (MM/DD/YYYY)",
          "Phase end date (MM/DD/YYYY)", "Linked station")


def exact_callsign(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("A callsign must be a nonempty string")
    # DT and TV can coexist as different service records (CHAN-DT-2 / CHAN-TV-2).
    return value.strip().upper()


def calendar_date(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("A record date must be YYYY-MM-DD")
    return date.fromisoformat(value)


class _TableRows(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows = []
        self.row = None
        self.cell = None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.row = []
        if tag in {"td", "th"} and self.row is not None:
            self.cell = []

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if tag in {"td", "th"} and self.cell is not None:
            self.row.append(" ".join("".join(self.cell).split()))
            self.cell = None
        if tag == "tr" and self.row is not None:
            self.rows.append(self.row)
            self.row = None


def schedule_records(html):
    """Read the ISED Annex A planning table without treating phases as events."""
    parser = _TableRows()
    parser.feed(html)
    if list(HEADER) not in parser.rows:
        raise ValueError("ISED transition table header is missing or changed")
    result = {}
    for row in parser.rows[parser.rows.index(list(HEADER)) + 1:]:
        if len(row) != len(HEADER):
            continue
        values = dict(zip(HEADER, row))
        # A trailing asterisk is a documented schedule footnote, not an alias.
        callsign = exact_callsign(row[0].removesuffix("*"))
        if callsign in result:
            raise ValueError(f"Duplicate schedule callsign: {callsign}")
        existing = re.fullmatch(r"(\d+) ([AD])", row[2])
        if (existing is None or not row[1].isdigit()
                or not 2 <= int(row[1]) <= 69
                or not 2 <= int(existing[1]) <= 69):
            raise ValueError(f"Invalid channel/mode record for {callsign}")
        result[callsign] = {
            "callsign": callsign, "raw": values,
            "existing_channel": int(existing[1]), "existing_mode": existing[2],
            "planned_dtv_channel": int(row[1]),
            "secondary_operation_footnote": row[0].endswith("*"),
            "evidence_kind": "planning_reference_not_actual_transition",
            "actual_transition_date": None,
        }
    return result


def cohort_from_workbook(path):
    """Re-extract exact identities from the original OOXML Appendix A bytes."""
    ns = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(path) as archive:
        shared = ["".join(node.itertext()) for node in ET.fromstring(
            archive.read("xl/sharedStrings.xml")).findall("s:si", ns)]
        rows = []
        for row in ET.fromstring(archive.read("xl/worksheets/sheet1.xml")).findall(".//s:row", ns):
            values = {}
            for cell in row:
                value = cell.find("s:v", ns)
                if value is not None:
                    text = shared[int(value.text)] if cell.get("t") == "s" else value.text
                    values[re.sub(r"\d+$", "", cell.get("r"))] = text
            if values:
                rows.append(values)
    if rows[0] != {"A": "Site #", "B": "Market ", "C": "Call"}:
        raise ValueError("Corus Appendix A header changed")
    result = [{"site_number": int(row["A"]), "market": row["B"],
               "callsign": exact_callsign(row["C"])} for row in rows[1:]]
    if [row["site_number"] for row in result] != list(range(1, 45)):
        raise ValueError("Corus Appendix A must contain all 44 ordered sites")
    if len({row["callsign"] for row in result}) != 44:
        raise ValueError("Corus Appendix A has duplicate identities")
    return result


def join_cohort(schedule, cohort):
    seen = set()
    result = []
    for member in cohort:
        callsign = exact_callsign(member["callsign"])
        if callsign in seen:
            raise ValueError("Duplicate cohort identity")
        seen.add(callsign)
        result.append({**member, "callsign": callsign,
                       "schedule": schedule.get(callsign),
                       "match": "exact_callsign" if callsign in schedule else "unresolved",
                       "verified_rf_interval": None})
    return result


def validate_history(data, base_dir):
    """Check evidence identities, date semantics and the explicit absence of RF spans."""
    base = Path(base_dir).resolve()
    if data.get("schema") != SCHEMA:
        raise ValueError("Unsupported history schema")
    calendar_date(data["review_date"])
    if data.get("verified_rf_intervals") != [] or data.get("allocation_null_intervals") != []:
        raise ValueError("The event-only schema cannot assert continuous RF/null intervals")
    sources = data["sources"]
    for source in sources.values():
        relative = Path(source["file"])
        resolved = (base / relative).resolve()
        if relative.is_absolute() or not resolved.is_relative_to(base):
            raise ValueError("Source file must stay inside the history project")
        if source["access_kind"] not in {
            "original_document", "derived_source_extract", "search_index_observation"
        }:
            raise ValueError("Unknown source access kind")
        if hashlib.sha256(resolved.read_bytes()).hexdigest() != source["sha256"]:
            raise ValueError("Source content hash mismatch")
        if not source["url"].startswith("https://"):
            raise ValueError("Source provenance requires its HTTPS URL")
    entities = {}
    for entity in data["entities"]:
        cs = exact_callsign(entity["callsign"])
        if cs != entity["callsign"] or cs in entities:
            raise ValueError("Entity callsigns must be exact, canonical and unique")
        ch = entity["reference_rf_channel"]
        if isinstance(ch, bool) or not isinstance(ch, int) or not 2 <= ch <= 69:
            raise ValueError("Invalid reference physical channel")
        if entity["reference_channel_source"] not in sources or not entity["unresolved"]:
            raise ValueError("Reference channels and unknown history need explicit evidence")
        entities[cs] = entity
    seen = set()
    for event in data["events"]:
        if event["id"] in seen:
            raise ValueError("Duplicate event identifier")
        seen.add(event["id"])
        if event["callsign"] not in entities or event["source_id"] not in sources:
            raise ValueError("Event must reference an exact entity and known source")
        if event["kind"] not in KINDS:
            raise ValueError("Unknown event kind")
        if event["verified_rf_interval"] is not None:
            raise ValueError("A record event is not a continuous RF interval")
        if event["timezone"] is not None:
            raise ValueError("This calendar-event release has no verified event time zones")
        if event["kind"] in MONTH_KINDS:
            start, end = calendar_date(event["earliest_date"]), calendar_date(event["latest_date_exclusive"])
            next_month = date(start.year + (start.month == 12), start.month % 12 + 1, 1)
            if event["date"] is not None or event["date_precision"] != "month" or start.day != 1 or end != next_month:
                raise ValueError("A reported month must preserve its full half-open calendar range")
        else:
            calendar_date(event["date"])
            if event["date_precision"] != "day" or event["earliest_date"] is not None or event["latest_date_exclusive"] is not None:
                raise ValueError("Administrative/record dates cannot become state spans")
    return data


def load_history(path):
    path = Path(path)
    data = validate_history(json.loads(path.read_text(encoding="utf-8")), path.parent)
    schedule = schedule_records((path.parent / data["sources"]["schedule"]["file"]).read_text(encoding="utf-8"))
    fcc = json.loads((path.parent / data["sources"]["fcc-notification"]["file"]).read_text(encoding="utf-8"))["facility"]
    for entity in data["entities"]:
        if entity["reference_channel_source"] == "schedule":
            record = schedule.get(entity["callsign"])
            expected_channel = record["existing_channel"] if record else None
        elif entity["reference_channel_source"] == "fcc-notification" and entity["callsign"] == fcc["callsign"]:
            expected_channel = int(fcc["channel"])
        else:
            raise ValueError("Reference channel source has no implemented exact-identity join")
        if entity["reference_rf_channel"] != expected_channel:
            raise ValueError("Reference channel differs from the exact source record")
    return data


def render_history(history_path, output_dir):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages
    from matplotlib.lines import Line2D

    history_path, output_dir = Path(history_path), Path(output_dir)
    data = load_history(history_path)
    extracted_cohort = cohort_from_workbook(history_path.parent / "sources/corus-2018-cohort.xls")
    stored_cohort = json.loads((history_path.parent / "sources/corus-cohort-extract.json").read_text(encoding="utf-8"))["cohort"]
    if extracted_cohort != stored_cohort:
        raise ValueError("Stored cohort differs from original Appendix A")
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = "transmitter-history-" + data["review_date"]
    pdf_path = output_dir / (stem + ".pdf")
    png_path = output_dir / (stem + ".png")
    appendix_path = output_dir / (stem + "-cohort.png")
    entities = sorted(data["entities"], key=lambda e: (e["reference_rf_channel"], e["callsign"]))
    rows = {e["callsign"]: i for i, e in enumerate(entities)}
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 12,
                         "pdf.fonttype": 42, "axes.spines.top": False,
                         "axes.spines.right": False})
    fig = plt.figure(figsize=(20, 11))
    ax = fig.add_axes([0.19, 0.27, 0.60, 0.57])
    fig.text(0.035, 0.95, "Transmitter history: dated evidence", fontsize=25, weight="bold", color="#142b3b")
    fig.text(0.035, 0.911, data["title"], fontsize=15, color="#45606d")
    fig.text(0.035, 0.876, "Markers describe source records. No connected line denotes continuous broadcasting or silence.", fontsize=12)
    colors = {"operator_on_month": "#c78410", "operator_shutdown_month": "#b33e46",
              "ised_date_field": "#087f8c", "administrative": "#365f9c", "filing_receipt": "#6d548e"}
    for i in range(len(entities)):
        if i % 2 == 0:
            ax.axhspan(i - .48, i + .48, color="#f0f4f5", zorder=0)
    points = []
    for event in data["events"]:
        y = rows[event["callsign"]]
        kind = event["kind"]
        if kind in MONTH_KINDS:
            lo, hi = [mdates.date2num(calendar_date(event[x])) for x in ("earliest_date", "latest_date_exclusive")]
            ax.plot([lo, hi], [y, y], color=colors[kind], lw=7, solid_capstyle="butt", zorder=4)
            marker = "^" if kind == "operator_on_month" else "v"
            ax.scatter([(lo + hi) / 2], [y], marker=marker, color=colors[kind], s=105, zorder=5)
            points.append({"id": event["id"], "kind": kind, "earliest_date": event["earliest_date"], "latest_date_exclusive": event["latest_date_exclusive"]})
        else:
            x = mdates.date2num(calendar_date(event["date"]))
            if kind == "ised_date_field":
                ax.scatter([x], [y], marker="o", edgecolor=colors[kind], facecolor="white", s=105, linewidth=2, zorder=5)
            else:
                ax.scatter([x], [y], marker="D" if kind == "administrative" else "s", color=colors[kind], s=74, zorder=5)
            points.append({"id": event["id"], "kind": kind, "date": event["date"]})
    ax.set_yticks(range(len(entities)), [f"{e['reference_rf_channel']:02d}   {e['callsign']}\n{e['city']}" for e in entities])
    ax.tick_params(axis="y", length=0, pad=13, labelsize=12)
    ax.set_ylim(len(entities) - .4, -.6)
    ax.set_xlim(date(2012, 1, 1), date(2026, 12, 1))
    ax.xaxis.set_major_locator(mdates.YearLocator(2))
    ax.xaxis.set_minor_locator(mdates.YearLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax.grid(axis="x", color="#d9e1e5", lw=.8)
    ax.grid(axis="x", which="minor", color="#ecf0f2", lw=.5)
    ax.set_xlabel("Calendar date carried by the source record (no invented UTC time)", labelpad=12)
    fig.text(.035, .846, "Reference RF channel / callsign", fontsize=11, weight="bold")
    fig.text(.81, .846, "What remains unknown", fontsize=11, weight="bold")
    for e in entities:
        ax.text(1.03, rows[e['callsign']], textwrap.fill(e['unresolved'], 27), transform=ax.get_yaxis_transform(), va="center", fontsize=11, color="#505963")
    handles = [
        Line2D([], [], marker="^", color=colors["operator_on_month"], linestyle="none", markersize=9, label="Operator on-air month (indexed report)"),
        Line2D([], [], marker="v", color=colors["operator_shutdown_month"], linestyle="none", markersize=9, label="Operator shutdown month (original brief)"),
        Line2D([], [], marker="o", color=colors["ised_date_field"], markerfacecolor="white", linestyle="none", markersize=9, label="ISED ON_AIR field (snapshot record)"),
        Line2D([], [], marker="D", color=colors["administrative"], linestyle="none", markersize=8, label="Administrative / certificate date"),
        Line2D([], [], marker="s", color=colors["filing_receipt"], linestyle="none", markersize=8, label="FCC filing receipt (not cessation)"),
    ]
    fig.legend(handles=handles, loc="lower left", bbox_to_anchor=(.035, .138), ncol=3, frameon=False, fontsize=11, columnspacing=2)
    fig.text(.035, .110, "The 2014 Shaw report gives October 2012; the current CHKL records carry 2013 ON_AIR dates. Both are shown, with the discrepancy unresolved.", fontsize=11)
    fig.text(.035, .084, "RF row labels are source-backed reference channels, not reconstructed channel trajectories. The short bar spans the reported month; its triangle marks no exact day.", fontsize=11)
    fig.text(.035, .057, "Sources: ISED transition schedule + Baserad (2026-09-02); Corus 2018/2019/2020 application records; CRTC 2019-209 / 2020-391; FCC LMS facility 35472.", fontsize=10, color="#45606d")
    fig.text(.035, .032, "Original and derived source hashes, indexed-only access, dates, exact identities and unresolved items accompany this plot in dtv-census/history. Review: " + data['review_date'], fontsize=10, color="#45606d")

    base = history_path.parent
    schedule = schedule_records((base / "sources/ised-transition-schedule.html").read_text(encoding="utf-8"))
    cohort = json.loads((base / "sources/corus-cohort-extract.json").read_text(encoding="utf-8"))["cohort"]
    joined = join_cohort(schedule, cohort)
    fig2 = plt.figure(figsize=(20, 12))
    fig2.text(.035, .95, "The 44-transmitter shutdown cohort", fontsize=25, weight="bold", color="#142b3b")
    fig2.text(.035, .913, "Operator-reported month: October 2018. Every exact shutdown day and later continuous state remains unknown.", fontsize=14)
    fig2.text(.035, .88, "Existing channel/mode and proposed DTV channel come from the ISED planning table. A planned channel is not an observed transition.", fontsize=12)
    for col, group in enumerate((joined[:22], joined[22:])):
        axis = fig2.add_axes([.035 + col * .49, .18, .46, .66])
        axis.axis("off")
        table_rows = []
        for item in group:
            s = item["schedule"]
            table_rows.append([str(item["site_number"]), item["callsign"], textwrap.fill(item["market"], 20),
                               f"{s['existing_channel']} {s['existing_mode']}" if s else "unknown",
                               str(s['planned_dtv_channel']) if s else "unknown"])
        table = axis.table(cellText=table_rows, colLabels=["#", "Exact callsign", "Community", "Existing", "Planned"],
                           colWidths=[.045, .235, .43, .14, .15], loc="center", cellLoc="left", bbox=[0, 0, 1, 1])
        table.auto_set_font_size(False)
        table.set_fontsize(10.5)
        for (r, c), cell in table.get_celld().items():
            cell.set_edgecolor("#d9e1e5")
            cell.set_linewidth(.45)
            if r == 0:
                cell.set_facecolor("#173a50")
                cell.set_text_props(color="white", weight="bold")
            else:
                item = group[r - 1]
                selected = item['callsign'] in {'CITM-DT', 'CHAN-DT-6', 'CKTN-DT-2'}
                cell.set_facecolor("#e5f2ec" if selected else ("#f4f6f7" if r % 2 == 0 else "white"))
    fig2.text(.035, .135, "A = analog; D = digital. Green rows are the three BC cohort records with existing digital channels 14-36, included in the overview.", fontsize=12)
    fig2.text(.035, .106, "Taghum: the independent ISED row says 23 D; the original engineering map's malformed CH232 label is preserved as a source error, not silently edited.", fontsize=11)
    fig2.text(.035, .079, "Identity guard: CRTC listed CHAN-DT-2 and CHAN-TV-2 together in 2017. Only the DT record enters this shutdown cohort; the later TV listing is not resumption evidence.", fontsize=11)
    fig2.text(.035, .047, "All 44 identities match by exact callsign. Phase deadlines, allotments, licence absence and this event table provide zero verified continuous off intervals.", fontsize=11, weight="bold", color="#173a50")
    fig2.text(.035, .025, "Sources: Corus application 2018-0936-0 Appendix A; ISED Digital Television Transition Schedule, date label 2017-04-12, retrieved 2026-09-09.", fontsize=10, color="#45606d")
    with PdfPages(pdf_path, metadata={"Title": data['title'], "Author": "dtv-census", "CreationDate": None, "ModDate": None}) as pdf:
        pdf.savefig(fig)
        pdf.savefig(fig2)
    fig.savefig(png_path, dpi=150)
    fig2.savefig(appendix_path, dpi=150)
    plt.close(fig)
    plt.close(fig2)
    receipt = {"schema": "dtv-history-plot-receipt-v1", "history_sha256": hashlib.sha256(history_path.read_bytes()).hexdigest(),
               "renderer_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
               "matplotlib_version": matplotlib.__version__,
               "source_hashes": {k: v["sha256"] for k, v in data["sources"].items()},
               "entity_count": len(entities), "event_count": len(points), "events": points,
               "cohort_exact_matches": sum(r['match'] == 'exact_callsign' for r in joined),
               "verified_rf_intervals": [], "allocation_null_intervals": [],
               "outputs": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (pdf_path, png_path, appendix_path)}}
    (output_dir / (stem + "-receipt.json")).write_text(json.dumps(receipt, indent=2) + "\n")
    (output_dir / (stem + "-cohort.json")).write_text(json.dumps(joined, indent=2) + "\n")
    return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("history", type=Path)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args(argv)
    if args.output_dir is None:
        data = load_history(args.history)
        print(f"Valid: {len(data['entities'])} exact identities, {len(data['events'])} events; zero RF intervals")
    else:
        print(json.dumps(render_history(args.history, args.output_dir), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
