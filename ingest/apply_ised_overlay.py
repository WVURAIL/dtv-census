#!/usr/bin/env python3
"""Regenerate census/census.csv: the workbook reduction plus the ISED overlay.

The reduction (census/census_from_xlsx.py) is faithful to the manually
compiled workbook. This overlay corrects its Canadian side against the
authoritative ISED licence records in sources/ised/ws_data.csv, applying the
verdicts recorded in census/VERIFICATION.md.  A licence is evidence that a
transmitter may operate, not proof that it was emitting at the snapshot time,
so every output row carries an explicit evidence_status:

  * coordinates: wherever a Canadian on-air row matches an ISED digital
    TV/LPTV licence (callsign, else transmitter position within 10 km), its
    distance and bearing are recomputed from the ISED site -- the workbook
    anchored many rows on the community instead of the transmitter;
  * status: Canadian workbook rows reported on air are retained only when a
    matching ISED digital licence exists; workbook rows typed "analog" whose
    station holds a digital ISED licence and in-radius licensed emitters absent
    from the workbook are retained as licensed_candidate, not silently called
    on-air;
  * ERP: a new erp_kw column carries the ISED effective radiated power for
    every matched Canadian row (blank for US rows until an FCC LMS ingest
    exists). census.csv keeps detectability_db, so
    `pilot-proxy analyze-transmitter-census` behaves exactly as before; its
    documented erp_kw scoring mode becomes available where field strengths
    are missing.

US rows pass through untouched. Every change is printed.

    python3 ingest/apply_ised_overlay.py
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "census"))
sys.path.insert(0, str(REPO / "ingest"))

from census_from_xlsx import (CENSUS_SCHEMA_VERSION, format_bearing, reduce,  # noqa: E402
                              write_csv)
from verify_against_ised import (DRAO, POSITION_TOL_KM, RADIUS_MI,   # noqa: E402
                                 WORKBOOK, canon_callsign,
                                 haversine_km, load_ised)

OUT = REPO / "census" / "census.csv"
CANADA = {"BC", "AB", "SK", "YT"}
PILOT_ABOVE_EDGE_MHZ = 0.309441          # matches the workbook's pilot column

# Stable, machine-readable evidence vocabulary.  Consumers can use all rows
# for the conservative maximum envelope, or exclude ``licensed_candidate``
# when they need a reported-on-air-only scenario.
REPORTED_ON_AIR_LICENSED = "reported_on_air_licensed"
REPORTED_ON_AIR_UNVERIFIED = "reported_on_air_unverified"
LICENSED_CANDIDATE = "licensed_candidate"


def bearing_deg(lat1, lon1, lat2, lon2):
    rad = math.radians
    dlon = rad(lon2 - lon1)
    y = math.sin(dlon) * math.cos(rad(lat2))
    x = (math.cos(rad(lat1)) * math.sin(rad(lat2))
         - math.sin(rad(lat1)) * math.cos(rad(lat2)) * math.cos(dlon))
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def pilot_mhz(ch):
    return 470.0 + 6.0 * (ch - 14) + PILOT_ABOVE_EDGE_MHZ


def chime_index(ch):
    return round((800.0 - pilot_mhz(ch)) * 1024.0 / 400.0)


def apply_site(row, st):
    """Rewrite a row's geometry (and ERP) from the ISED licence record.
    Returns the km shift for rows that already carried a distance."""
    km = haversine_km(*DRAO, st["lat"], st["lon"])
    old = float(row["distance_km"]) if row.get("distance_km") else km
    row["distance_km"] = f"{km:.1f}"
    row["bearing_deg"] = format_bearing(bearing_deg(*DRAO, st["lat"], st["lon"]))
    row["erp_kw"] = f"{10 ** (st['erp_dbw'] / 10) / 1e3:.3f}" \
        if not math.isnan(st["erp_dbw"]) else ""
    return old - km


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--output",
        type=Path,
        default=OUT,
        help="Output CSV (default: census/census.csv).",
    )
    args = parser.parse_args(argv)

    df = pd.read_excel(WORKBOOK)
    rows, stats = reduce(df)
    stations, analog_by_base, _other, _n = load_ised()
    by_key = {(s["base"], s["channel"]): s for s in stations}

    kept, dropped = [], []
    covered = set()
    n_matched = n_moved = 0
    for row in rows:
        if row["state_prov"] not in CANADA:
            row["erp_kw"] = ""
            row["evidence_status"] = REPORTED_ON_AIR_UNVERIFIED
            kept.append(row)
            continue
        bases = [canon_callsign(p)[0] for p in row["callsign"].split("+")]
        st = next((by_key[(b, row["rf_channel"])] for b in bases
                   if (b, row["rf_channel"]) in by_key), None)
        if st is None and row["latitude"] != "" and row["longitude"] != "":
            st = next((s for s in stations
                       if s["channel"] == row["rf_channel"]
                       and haversine_km(row["latitude"], row["longitude"],
                                        s["lat"], s["lon"]) <= POSITION_TOL_KM),
                      None)
        if st is None:
            dropped.append(row)
            print(f"DROP {row['callsign']} ch{row['rf_channel']} "
                  f"{row['city']} {row['state_prov']}: no current ISED "
                  f"digital licence")
            continue
        dkm = apply_site(row, st)
        row["evidence_status"] = REPORTED_ON_AIR_LICENSED
        covered.add((st["base"], st["channel"]))
        n_matched += 1
        if abs(dkm) > 1.0:
            n_moved += 1
            print(f"MOVE {row['callsign']} ch{row['rf_channel']} "
                  f"{row['city']}: distance {float(row['distance_km']) + dkm:.1f}"
                  f" -> {row['distance_km']} km (ISED site {st['callsign']})")
        kept.append(row)

    # promotions: workbook-analog stations holding a digital ISED licence
    promoted = []
    seen_promo = set()
    ca_analog = df[(df["Type"] == "analog") & df["State/Prov"].isin(CANADA)]
    for _, r in ca_analog.iterrows():
        base, _aux = canon_callsign(r["Call Sign"])
        for st in stations:
            if st["base"] != base or (base, st["channel"]) in covered \
                    or (base, st["channel"]) in seen_promo:
                continue
            seen_promo.add((base, st["channel"]))
            fs = r["Field Strength (dBuV/m)"]
            row = {
                "schema_version": CENSUS_SCHEMA_VERSION,
                "rf_channel": st["channel"],
                "callsign": str(r["Call Sign"]).strip(),
                "service_class": str(r["Class"]).strip(),
                "detectability_db": ("" if pd.isna(fs) else f"{float(fs):.2f}"),
                "frequency_tolerance": str(r["Frequency Tolerance"]).strip(),
                "chime_ch_index": str(chime_index(st["channel"])),
                "nominal_pilot_mhz": f"{pilot_mhz(st['channel']):.6f}",
                "city": str(r["City"]).strip(),
                "state_prov": str(r["State/Prov"]).strip(),
            }
            apply_site(row, st)
            row["evidence_status"] = LICENSED_CANDIDATE
            promoted.append(row)
            print(f"PROMOTE {row['callsign']} ch{st['channel']} "
                  f"{row['city']}: workbook analog, ISED digital "
                  f"({st['callsign']}, {row['distance_km']} km)")

    # additions: in-radius ISED digital emitters with no workbook trace
    added = []
    for st in sorted(stations, key=lambda s: s["drao_mi"]):
        key = (st["base"], st["channel"])
        if st["drao_mi"] > RADIUS_MI or key in covered or key in seen_promo:
            continue
        row = {
            "schema_version": CENSUS_SCHEMA_VERSION,
            "rf_channel": st["channel"],
            "callsign": st["callsign"],
            "service_class": ("Full-power" if st["record_type"] == "TV"
                              else st["record_type"]),
            "detectability_db": "",
            "frequency_tolerance": "None specified",
            "chime_ch_index": str(chime_index(st["channel"])),
            "nominal_pilot_mhz": f"{pilot_mhz(st['channel']):.6f}",
            "city": st["name"],
            "state_prov": st["prov"],
        }
        apply_site(row, st)
        row["evidence_status"] = LICENSED_CANDIDATE
        added.append(row)
        print(f"ADD {st['callsign']} ch{st['channel']} {st['name']} "
              f"{st['prov']}: ISED {st['record_type']} licence, no workbook "
              f"row ({row['distance_km']} km)")

    final = kept + promoted + added
    write_csv(final, args.output, extra_fields=["erp_kw", "evidence_status"])
    print(f"\nreduction: {len(rows)} rows "
          f"({stats['n_merged']} share-merges); overlay: {n_matched} "
          f"Canadian rows matched to ISED ({n_moved} moved > 1 km), "
          f"{len(dropped)} dropped, {len(promoted)} promoted, "
          f"{len(added)} added; erp_kw on "
          f"{sum(1 for r in final if r.get('erp_kw'))} rows")
    print("evidence: "
          f"{sum(r.get('evidence_status') == REPORTED_ON_AIR_LICENSED for r in final)} "
          "reported-on-air + licensed, "
          f"{sum(r.get('evidence_status') == REPORTED_ON_AIR_UNVERIFIED for r in final)} "
          "reported-on-air unverified, "
          f"{sum(r.get('evidence_status') == LICENSED_CANDIDATE for r in final)} "
          "licensed candidates")
    print(f"final: {len(final)} emitter-channel rows -> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
