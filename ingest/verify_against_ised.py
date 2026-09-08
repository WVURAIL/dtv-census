#!/usr/bin/env python3
"""Cross-check the census workbook's Canadian rows against ISED's records.

The census workbook is a manual compilation (see census/PROVENANCE.md). For
the Canadian side there is an authoritative, machine-readable counterpart:
``sources/ised/ws_data.csv``, the White Space Data Extract's "Television and
Other Licensed Service Stations" table (schema:
``sources/ised/field_descriptions/ws_field_desc.pdf``; 19 columns, no header;
WGS84 coordinates in D:M:S with west-positive longitude; ERP in dBW; centre
frequency in MHz). This script verifies the workbook against it, both ways:

  * every on-air Canadian workbook row should have an ISED digital record on
    the same physical channel — matched by callsign (after normalising the
    two conventions: ISED ``CHKL-DT-1`` is RabbitEars ``CHKL-1``) and by
    transmitter position;
  * every ISED digital UHF (14-36) station within 500 statute miles of DRAO
    should appear in the workbook — anything else is a census candidate the
    compilation missed.

ISED ``...AX<n>`` records are auxiliary/backup transmitters and are folded
into their main record. The extract covers Canada only; the workbook's US
rows (FCC LMS territory) are out of scope here.

Requires pandas + openpyxl (for the workbook).

    python3 ingest/verify_against_ised.py
    python3 ingest/verify_against_ised.py --csv /tmp/ised_crosscheck.csv
"""
from __future__ import annotations

import argparse
import csv
import math
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
WORKBOOK = REPO / "census" / "TV_Stations_UHF_within500mi_DRAO.xlsx"
WS_DATA = REPO / "sources" / "ised" / "ws_data.csv"

DRAO = (49.3208, -119.6239)          # census/PROVENANCE.md
RADIUS_MI = 500.0                    # the census inclusion radius
POSITION_TOL_KM = 10.0               # same-site tolerance for matching
UHF = range(14, 37)

# ws_data.csv columns (0-based), per ws_field_desc.pdf
C_RECORD_TYPE = 0    # 1 TV, 2 RRBS/protected, 3 non-protected, 4 LPA, 5 LPTV
C_STATION_NAME = 4   # the community the licence names
C_CALLSIGN = 5
C_LAT = 8            # D:M:S, WGS84
C_LON = 9            # D:M:S, west positive
C_PROVINCE = 12
C_ERP_DBW = 13
C_FLAG = 15          # A analog / D digital
C_FREQ_MHZ = 18      # centre frequency
RECORD_TYPE = {"1": "TV", "2": "RRBS", "3": "non-protected", "4": "LPA",
               "5": "LPTV"}


def haversine_km(lat1, lon1, lat2, lon2):
    rad = math.radians
    a = (math.sin(rad(lat2 - lat1) / 2) ** 2
         + math.cos(rad(lat1)) * math.cos(rad(lat2))
         * math.sin(rad(lon2 - lon1) / 2) ** 2)
    # Roundoff can put an antipodal pair just outside asin's domain.
    return 6371.0088 * 2 * math.asin(math.sqrt(min(max(a, 0.0), 1.0)))


def dms_to_deg(s):
    d, m, sec = (float(x) for x in str(s).split(":"))
    if not all(math.isfinite(x) for x in (d, m, sec)) \
            or d < 0 or not 0 <= m < 60 or not 0 <= sec < 60:
        raise ValueError(f"invalid unsigned D:M:S coordinate: {s!r}")
    return d + m / 60 + sec / 3600


def canon_callsign(cs):
    """Common form of a callsign across the two conventions, plus an
    auxiliary-transmitter flag: ISED 'CHKL-DT-1AX1' == RabbitEars 'CHKL-1',
    'CBUT-DT-AX1' == 'CBUT', 'CFEG-TV' == 'CFEG-DT' == 'CFEG'."""
    s = str(cs).strip().upper()
    aux = bool(re.search(r"AX\d*$", s))
    s = re.sub(r"-?AX\d*$", "", s)
    s = re.sub(r"-(DT|TV)(?=$|-)", "", s)
    return s, aux


def workbook_channels(cell):
    return [int(t) for t in re.findall(r"\d+", str(cell)) if int(t) in UHF]


def load_ised():
    """UHF records with usable coordinates, deduped: one main record per
    (callsign, channel); auxiliaries and repeated authorizations folded in,
    keeping the highest ERP. Returns (digital TV/LPTV/LPA emitters,
    analog-by-base lookup, other in-band services, raw digital count)."""
    raw = []
    analog_by_base = {}
    with open(WS_DATA, newline="", encoding="utf-8", errors="replace") as fh:
        for r in csv.reader(fh):
            if len(r) < 19:
                continue
            try:
                f = float(r[C_FREQ_MHZ])
            except ValueError:
                continue
            if not 470.0 <= f < 608.0:
                continue
            base, aux = canon_callsign(r[C_CALLSIGN])
            ch = int((f - 470) // 6) + 14
            if r[C_FLAG] != "D":
                analog_by_base.setdefault(base, set()).add(ch)
                continue
            try:
                lat, lon = dms_to_deg(r[C_LAT]), -dms_to_deg(r[C_LON])
                if not 0 <= lat <= 90 or not -180 <= lon <= 0:
                    continue
            except (ValueError, AttributeError):
                continue
            try:
                erp_dbw = float(r[C_ERP_DBW])
                if not math.isfinite(erp_dbw):
                    erp_dbw = float("nan")
            except ValueError:
                erp_dbw = float("nan")
            raw.append(dict(
                callsign=r[C_CALLSIGN], base=base, aux=aux, channel=ch,
                name=r[C_STATION_NAME].strip(),
                lat=lat, lon=lon, prov=r[C_PROVINCE], erp_dbw=erp_dbw,
                record_type=RECORD_TYPE.get(r[C_RECORD_TYPE],
                                            r[C_RECORD_TYPE]),
                drao_mi=haversine_km(*DRAO, lat, lon) / 1.609344))
    merged = {}
    for rec in raw:
        # one licensed emitter can carry several authorizations and an aux
        # transmitter: fold everything with the same station+channel into
        # one record (sites of one licence differ by a few km at most)
        key = (rec["base"], rec["channel"])
        keep = merged.get(key)
        if keep is None:
            merged[key] = dict(rec, n_records=1)
        else:
            keep["n_records"] += 1
            def priority(record):
                erp = record["erp_dbw"]
                return (not record["aux"],
                        erp if math.isfinite(erp) else -math.inf)

            if priority(rec) > priority(keep):
                # Geometry, distance and service metadata must come from the
                # same selected authorization, including when an aux came first.
                keep.update(rec)
    stations = [e for e in merged.values()
                if e["record_type"] in ("TV", "LPTV", "LPA")]
    other = [e for e in merged.values()
             if e["record_type"] not in ("TV", "LPTV", "LPA")]
    return stations, analog_by_base, other, len(raw)


def load_workbook():
    import pandas as pd
    wb = pd.read_excel(WORKBOOK)
    ca = wb[wb["State/Prov"].isin(["BC", "AB", "SK", "YT"])]
    rows = []
    for _, r in ca.iterrows():
        base, _ = canon_callsign(r["Call Sign"])
        lat, lon = r["Latitude"], r["Longitude"]
        has_pos = not (math.isnan(float(lat)) or math.isnan(float(lon)))
        for ch in workbook_channels(r["Physical Ch(s)"]):
            rows.append(dict(
                callsign=str(r["Call Sign"]).strip(), base=base, channel=ch,
                type=str(r["Type"]).strip(), cls=str(r["Class"]).strip(),
                city=str(r["City"]).strip(), prov=str(r["State/Prov"]),
                lat=float(lat) if has_pos else None,
                lon=float(lon) if has_pos else None,
                wb_mi=float(r["Distance to DRAO (mi)"])))
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--csv", type=Path, default=None,
                    help="also write the matched-pair table to this path")
    args = ap.parse_args(argv)

    ised, analog_by_base, other, n_raw = load_ised()
    wb_all = load_workbook()
    wb = [r for r in wb_all if r["type"] == "on-air"]
    print(f"ISED digital UHF records: {n_raw} raw -> "
          f"{len(ised) + len(other)} emitters after folding auxiliaries/"
          f"duplicate authorizations ({len(ised)} TV/LPTV/LPA, "
          f"{len(other)} RRBS/non-protected data services)")
    print(f"workbook Canadian emitter-channel rows: {len(wb_all)} "
          f"({len(wb)} on-air; the rest analog/off-air)\n")

    pairs, no_match = [], []
    for row in wb:
        cands = [e for e in ised if e["channel"] == row["channel"]]
        by_call = [e for e in cands if e["base"] == row["base"]]
        by_pos = []
        if row["lat"] is not None:
            by_pos = [e for e in cands if haversine_km(
                row["lat"], row["lon"], e["lat"], e["lon"]) <= POSITION_TOL_KM]
        chosen, how = None, None
        both = [e for e in by_call if e in by_pos]
        if both:
            chosen, how = both[0], "callsign+position"
        elif by_call:
            chosen, how = min(by_call, key=lambda e: haversine_km(
                row["lat"] or DRAO[0], row["lon"] or DRAO[1],
                e["lat"], e["lon"])), "callsign only (position differs)"
        elif by_pos:
            chosen, how = by_pos[0], "position only (callsign differs)"
        if chosen is None:
            no_match.append(row)
        else:
            off = (haversine_km(row["lat"], row["lon"],
                                chosen["lat"], chosen["lon"])
                   if row["lat"] is not None else float("nan"))
            pairs.append((row, chosen, how, off))

    matched_keys = {(e["base"], e["channel"]) for _, e, _, _ in pairs}
    missing = [e for e in ised
               if (e["base"], e["channel"]) not in matched_keys
               and e["drao_mi"] <= RADIUS_MI]

    exact = [p for p in pairs if p[2] == "callsign+position"]
    print(f"== workbook -> ISED: {len(exact)}/{len(wb)} rows confirmed by "
          f"callsign AND position (<= {POSITION_TOL_KM:g} km)")
    for row, e, how, off in pairs:
        if how != "callsign+position":
            print(f"  [{how}] {row['callsign']} ch{row['channel']} "
                  f"{row['city']} {row['prov']}: workbook pos vs ISED "
                  f"{e['callsign']} offset {off:.1f} km "
                  f"(workbook {row['wb_mi']:.0f} mi vs ISED "
                  f"{e['drao_mi']:.1f} mi from DRAO)")
    for row in no_match:
        hints = []
        if row["base"] in analog_by_base:
            chs = ",".join(str(c) for c in sorted(analog_by_base[row["base"]]))
            hints.append(f"ISED lists {row['base']} as ANALOG on ch {chs}")
        same_ch = [e for e in ised if e["channel"] == row["channel"]
                   and row["lat"] is not None]
        if same_ch:
            near = min(same_ch, key=lambda e: haversine_km(
                row["lat"], row["lon"], e["lat"], e["lon"]))
            hints.append(f"nearest same-channel digital: {near['callsign']} "
                         f"at {haversine_km(row['lat'], row['lon'], near['lat'], near['lon']):.0f} km")
        hint = ("; ".join(hints)) or "no ISED trace at all"
        print(f"  [NO ISED RECORD] {row['callsign']} ch{row['channel']} "
              f"{row['city']} {row['prov']} ({row['cls']}, "
              f"{row['wb_mi']:.0f} mi) -- {hint}")

    wb_analog = {r["base"] for r in wb_all if r["type"] != "on-air"}
    print(f"\n== ISED -> workbook: digital TV/LPTV emitters within "
          f"{RADIUS_MI:g} mi with no on-air workbook row: {len(missing)}")
    for e in sorted(missing, key=lambda e: e["drao_mi"]):
        note = (" -- workbook lists this station as analog/off-air"
                if e["base"] in wb_analog else "")
        print(f"  {e['callsign']} ch{e['channel']} "
              f"({e['record_type']}, {e['prov']}, {e['drao_mi']:.0f} mi, "
              f"ERP {e['erp_dbw']:.1f} dBW){note}")

    other_in = sorted((e for e in other if e["drao_mi"] <= RADIUS_MI),
                      key=lambda e: e["drao_mi"])
    print(f"\n== not TV stations, but licensed in-band (RRBS/non-protected "
          f"data services within {RADIUS_MI:g} mi): {len(other_in)}")
    for e in other_in[:10]:
        print(f"  {e['callsign'] or '(no callsign)'} ch{e['channel']} "
              f"({e['record_type']}, {e['prov']}, {e['drao_mi']:.0f} mi)")
    if len(other_in) > 10:
        print(f"  ... and {len(other_in) - 10} more")

    offs = [off for _, _, _, off in pairs if not math.isnan(off)]
    if offs:
        offs.sort()
        print(f"\ncoordinate offsets over {len(offs)} matches: median "
              f"{offs[len(offs)//2]:.2f} km, max {offs[-1]:.2f} km")

    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["wb_callsign", "channel", "city", "prov", "match",
                        "ised_callsign", "offset_km", "wb_mi_drao",
                        "ised_mi_drao", "ised_erp_dbw", "ised_erp_kw",
                        "record_type"])
            for row, e, how, off in pairs:
                w.writerow([row["callsign"], row["channel"], row["city"],
                            row["prov"], how, e["callsign"],
                            f"{off:.2f}", f"{row['wb_mi']:.1f}",
                            f"{e['drao_mi']:.1f}", f"{e['erp_dbw']:.2f}",
                            f"{10 ** (e['erp_dbw'] / 10) / 1e3:.2f}",
                            e["record_type"]])
        print(f"wrote {args.csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
