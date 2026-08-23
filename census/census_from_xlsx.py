#!/usr/bin/env python3
# coding=utf-8
"""Convert TV_Stations_UHF_within500mi_DRAO.xlsx to the census CSV consumed by
`pilot-proxy analyze-transmitter-census`.

Policy (each choice reported on stdout):
  * population = Type == "on-air" only: off-air stations emit nothing, analog
    NTSC has no ATSC pilot, and ATSC 3.0 (OFDM) carries no 8-VSB pilot tone;
  * "Physical Ch(s)" may list several channels ("Sh. 24", "9; 23, 25"): every
    integer token in the UHF DTV range 14..36 becomes one output row (a
    station transmitting on two channels is two potential carriers);
  * detectability_db = Field Strength (dBuV/m) where modeled, blank otherwise
    (the analysis ranks blanks last, tie-broken by distance);
  * distance converted miles -> km; bearing, tolerance, CHIME channel index,
    and location carried through as extra columns.

This is the reduction stage only. The committed census.csv additionally
carries the ISED overlay (Canadian site coordinates, licence-status
adjudication, and ERP): regenerate it with ingest/apply_ised_overlay.py,
which imports the reduction from here.

Usage: census_from_xlsx.py <input.xlsx> <output.csv>
"""
from __future__ import annotations

import csv
import re
import sys

import pandas as pd

MI_TO_KM = 1.609344
UHF_RANGE = range(14, 37)
CENSUS_SCHEMA_VERSION = "dtv_transmitter_census_v1"

# the public census.csv schema, in column order; reduce() rows additionally
# carry workbook latitude/longitude for the overlay's position matching
CSV_FIELDS = ["schema_version", "rf_channel", "callsign", "service_class", "detectability_db",
              "distance_km", "bearing_deg", "frequency_tolerance",
              "chime_ch_index", "nominal_pilot_mhz", "city", "state_prov"]


def channels(cell) -> list[int]:
    return [c for c in (int(t) for t in re.findall(r"\d+", str(cell)))
            if c in UHF_RANGE]


def reduce(df: pd.DataFrame):
    """The deterministic reduction: on-air rows -> merged emitter-channel
    rows. Returns (rows, stats); rows carry the CSV_FIELDS plus workbook
    'latitude'/'longitude' (float or '') for downstream position matching."""
    n0 = len(df)
    kept = df[df["Type"] == "on-air"]
    dropped = df[df["Type"] != "on-air"]["Type"].value_counts().to_dict()
    rows, no_uhf = [], []
    for _, r in kept.iterrows():
        chans = channels(r["Physical Ch(s)"])
        if not chans:
            no_uhf.append(str(r["Call Sign"]))
            continue
        fs = r["Field Strength (dBuV/m)"]
        for ch in chans:
            rows.append({
                "schema_version": CENSUS_SCHEMA_VERSION,
                "rf_channel": ch,
                "callsign": str(r["Call Sign"]).strip(),
                "service_class": str(r["Class"]).strip(),
                "detectability_db": ("" if pd.isna(fs) else f"{float(fs):.2f}"),
                "distance_km": f"{float(r['Distance to DRAO (mi)']) * MI_TO_KM:.1f}",
                "bearing_deg": f"{float(r['Bearing from DRAO (deg, True)']):.1f}",
                "frequency_tolerance": str(r["Frequency Tolerance"]).strip(),
                "chime_ch_index": ("" if pd.isna(r["CHIME Ch Index"])
                                   else str(int(r["CHIME Ch Index"]))),
                "nominal_pilot_mhz": f"{float(r['Nominal Pilot Freq (MHz)']):.6f}",
                "city": str(r["City"]).strip(),
                "state_prov": str(r["State/Prov"]).strip(),
                "latitude": ("" if pd.isna(r["Latitude"])
                             else float(r["Latitude"])),
                "longitude": ("" if pd.isna(r["Longitude"])
                              else float(r["Longitude"])),
            })

    # Channel-sharing partners (same rf_channel at the same site) emit ONE
    # physical carrier with one pilot: merge them into a single emitter row,
    # keeping the more primary class and joining callsigns.
    def _rank(c):
        return 0 if c == "Full-power" else 1
    merged, seen = [], {}
    for row in rows:
        key = (row["rf_channel"], row["city"], row["state_prov"],
               row["distance_km"], row["bearing_deg"])
        if key in seen:
            keep = seen[key]
            keep["callsign"] += "+" + row["callsign"]
            if _rank(row["service_class"]) < _rank(keep["service_class"]):
                keep["service_class"] = row["service_class"]
            if row["detectability_db"] and (not keep["detectability_db"] or
                    float(row["detectability_db"]) > float(keep["detectability_db"])):
                keep["detectability_db"] = row["detectability_db"]
        else:
            seen[key] = row
            merged.append(row)
    stats = dict(n_input=n0, n_kept=len(kept), dropped_by_type=dropped,
                 no_uhf=no_uhf, n_merged=len(rows) - len(merged))
    return merged, stats


def write_csv(rows: list[dict], dst, extra_fields: list[str] = ()) -> None:
    fields = CSV_FIELDS + list(extra_fields)
    # Spell out both encoding and line terminator so regeneration is
    # byte-identical on Linux, macOS, and Windows.  The source contains the
    # non-ASCII plus/minus sign in its frequency-tolerance field.
    with open(dst, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore",
                           lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def main(argv: list[str]) -> int:
    src, dst = argv
    rows, s = reduce(pd.read_excel(src))
    write_csv(rows, dst)
    print(f"input rows: {s['n_input']}; on-air kept: {s['n_kept']}; "
          f"dropped by type: {s['dropped_by_type']}")
    if s["no_uhf"]:
        print(f"on-air rows with no UHF 14..36 channel token (skipped): "
              f"{s['no_uhf']}")
    print(f"channel-sharing partners merged into single emitters: "
          f"{s['n_merged']}")
    print(f"output rows (one per physical emitter-channel): {len(rows)} "
          f"-> {dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
