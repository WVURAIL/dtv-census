#!/usr/bin/env python3
"""Load US UHF ATSC 1.0 licensed sites from an FCC LMS public snapshot.

Accept a directory of the six named .dat files (or individual table .zip
files), or a combined LMS ZIP. See sources/fcc/README.md for the join and
selection policy. No downloads occur during loading. The output is a
licence-supported candidate table, not evidence of an observed emission.
"""
from __future__ import annotations

import argparse
import csv
import io
import math
from collections import Counter
from contextlib import ExitStack
from datetime import date
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from apply_ised_overlay import bearing_deg, chime_index, pilot_mhz
from census_from_xlsx import CENSUS_SCHEMA_VERSION, format_bearing, write_csv
from verify_against_ised import DRAO, RADIUS_MI, dms_to_deg, haversine_km

SERVICES = {
    "DTV": "Full-power", "DTS": "Full-power",
    "DCA": "Class A", "DC": "Class A", "CA": "Class A", "CADTS": "Class A",
    "LPD": "LPTV", "LD": "LPTV", "LDTS": "LPTV",
    "LPT": "Translator", "TX": "Translator", "DRT": "Translator",
    "TDTS": "Translator",
}
LICENSED_STATUSES = {"LICEN", "LICRP"}
TABLE_FIELDS = {
    "facility": "active_ind facility_id callsign service_code facility_status "
                "latest_filing_version_id license_filing_id atsc3_ind "
                "community_served_city community_served_state",
    "license_filing_version": "active_ind filing_version_id license_filing_id "
                              "auth_type_code current_status_code service_code",
    "application_facility": "active_ind afac_application_id afac_facility_id "
                            "afac_channel country_code atsc3_ind",
    "app_location": "aloc_active_ind aloc_aapp_application_id aloc_loc_record_id "
                    "aloc_dts_reference_location_ind aloc_lat_deg aloc_lat_mm "
                    "aloc_lat_ss aloc_lat_dir aloc_long_deg aloc_long_mm "
                    "aloc_long_ss aloc_long_dir",
    "app_antenna": "aant_active_ind aant_antenna_record_id aant_aloc_loc_record_id",
    "app_antenna_frequency": "aafq_active_ind aafq_aant_antenna_record_id "
                            "aafq_channel aafq_power_erp_kw aafq_max_erp_kw "
                            "aafq_horiz_erp_kw aafq_vert_erp_kw",
}
EXTRA_FIELDS = ["erp_kw", "evidence_status", "latitude", "longitude",
                "coordinate_datum", "facility_id", "application_id", "site_id",
                "license_filing_id", "fcc_service", "fcc_status", "source",
                "snapshot_date"]


def table_rows(source: Path, table: str):
    """Stream headered, unquoted pipe records; tolerate the FCC |^| trailer.

    Columns are resolved by name, never by the PDF's alphabetical ordering.
    Schema/record corruption is fatal with file and line context.
    """
    source = Path(source)
    with ExitStack() as stack:
        data = source / f"{table}.dat"
        if source.is_dir() and data.is_file():
            stream = stack.enter_context(data.open(encoding="utf-8-sig", newline=""))
        else:
            archive = source / f"{table}.zip" if source.is_dir() else source
            zipped = stack.enter_context(ZipFile(archive))
            members = [name for name in zipped.namelist()
                       if Path(name).name.lower() == f"{table}.dat"]
            if len(members) != 1:
                raise ValueError(f"{archive}: expected exactly one {table}.dat")
            binary = stack.enter_context(zipped.open(members[0]))
            stream = stack.enter_context(io.TextIOWrapper(binary, encoding="utf-8-sig",
                                                          newline=""))
        reader = csv.reader(stream, delimiter="|", quoting=csv.QUOTE_NONE)

        def strip_trailer(row):
            return row[:-2] if row[-2:] == ["^", ""] else row

        header = [v.strip().lower() for v in strip_trailer(next(reader, []))]
        missing = set(TABLE_FIELDS[table].split()) - set(header)
        if missing or len(header) != len(set(header)):
            raise ValueError(f"{table}.dat: invalid header; missing {sorted(missing)} "
                             "or duplicate columns")
        for row in reader:
            if not row:
                continue
            row = strip_trailer(row)
            if len(row) != len(header):
                raise ValueError(f"{table}.dat:{reader.line_num}: expected "
                                 f"{len(header)} fields, got {len(row)}")
            yield dict(zip(header, (value.strip() for value in row)))


def coordinate(row, axis):
    prefix = f"aloc_{axis}_"
    degrees = dms_to_deg(":".join(row[prefix + part] for part in ("deg", "mm", "ss")))
    direction = row[prefix + "dir"].upper()
    allowed, limit = ("NS", 90) if axis == "lat" else ("EW", 180)
    if direction not in tuple(allowed) or degrees > limit:
        raise ValueError(f"invalid {axis} coordinate")
    return -degrees if direction in ("S", "W") else degrees


def erp_kw(row):
    # TV's total ERP wins when supplied. Do not add H/V polarization powers:
    # that would double-count the same authorized transmitter.
    for field in ("aafq_power_erp_kw", "aafq_max_erp_kw"):
        if row[field]:
            value = float(row[field])
            if not math.isfinite(value) or value < 0:
                raise ValueError("invalid ERP")
            return value
    values = [float(row[field]) for field in ("aafq_horiz_erp_kw", "aafq_vert_erp_kw")
              if row[field]]
    if any(not math.isfinite(value) or value < 0 for value in values):
        raise ValueError("invalid ERP")
    return max(values) if values else None


def load_fcc_lms(source, *, snapshot_date, radius_mi=RADIUS_MI, center=DRAO):
    """Return (census-compatible site rows, diagnostic counts).

    Select the facility's current filing pointer, require that exact filing
    to be an active granted licence, then join its US application, locations,
    antennas and channel/power records. Do not choose a newer pending CP or
    fall back to an unrelated historical authorization when a join is absent.
    """
    snapshot_date = date.fromisoformat(snapshot_date).isoformat()
    if not math.isfinite(radius_mi) or radius_mi < 0:
        raise ValueError("radius must be finite and non-negative")
    if len(center) != 2 or not all(math.isfinite(v) for v in center) \
            or not -90 <= center[0] <= 90 or not -180 <= center[1] <= 180:
        raise ValueError("invalid center coordinates")
    stats = Counter()
    facilities = {}
    for row in table_rows(source, "facility"):
        stats["facilities_seen"] += 1
        if row["active_ind"] != "Y" or row["service_code"] not in SERVICES \
                or row["facility_status"] not in LICENSED_STATUSES \
                or row["atsc3_ind"] == "Y" or not row["callsign"]:
            continue
        key = row["latest_filing_version_id"]
        if not key or not row["facility_id"] or not row["license_filing_id"]:
            stats["missing_identifiers"] += 1
            continue
        if key in facilities and facilities[key] != row:
            raise ValueError(f"conflicting facility rows for filing {key}")
        facilities[key] = row
    stats["eligible_facilities"] = len(facilities)

    licensed = set()
    for row in table_rows(source, "license_filing_version"):
        key = row["filing_version_id"]
        facility = facilities.get(key)
        if facility and row["active_ind"] == "Y" and row["auth_type_code"] == "L" \
                and row["current_status_code"] == "GRA" \
                and row["service_code"] in SERVICES \
                and row["license_filing_id"] == facility["license_filing_id"]:
            licensed.add(key)
    stats["licensed_filings"] = len(licensed)

    applications = {}
    for row in table_rows(source, "application_facility"):
        key = row["afac_application_id"]
        if key in licensed and row["active_ind"] == "Y" \
                and row["country_code"] == "US" and row["atsc3_ind"] != "Y" \
                and row["afac_facility_id"] == facilities[key]["facility_id"]:
            if key in applications and applications[key] != row:
                raise ValueError(f"conflicting application_facility rows for {key}")
            applications[key] = row
    stats["us_applications"] = len(applications)

    locations = {}
    for row in table_rows(source, "app_location"):
        key = row["aloc_aapp_application_id"]
        if key not in applications or row["aloc_active_ind"] != "Y" \
                or row["aloc_dts_reference_location_ind"] == "Y":
            continue
        try:
            lat, lon = coordinate(row, "lat"), coordinate(row, "long")
        except ValueError:
            stats["invalid_coordinates"] += 1
            continue
        distance = haversine_km(*center, lat, lon)
        if distance / 1.609344 > radius_mi:
            stats["outside_radius"] += 1
            continue
        site_id = row["aloc_loc_record_id"]
        if not site_id:
            stats["missing_identifiers"] += 1
            continue
        site = (key, lat, lon, distance)
        if site_id in locations and locations[site_id] != site:
            raise ValueError(f"conflicting location rows for {site_id}")
        locations[site_id] = site
    stats["in_radius_sites"] = len(locations)

    antennas = {}
    for row in table_rows(source, "app_antenna"):
        site_id = row["aant_aloc_loc_record_id"]
        if site_id in locations and row["aant_active_ind"] == "Y":
            key = row["aant_antenna_record_id"]
            if not key:
                stats["missing_identifiers"] += 1
                continue
            if key in antennas and antennas[key] != site_id:
                raise ValueError(f"conflicting antenna rows for {key}")
            antennas[key] = site_id

    emitters = {}
    for row in table_rows(source, "app_antenna_frequency"):
        site_id = antennas.get(row["aafq_aant_antenna_record_id"])
        if site_id is None or row["aafq_active_ind"] != "Y":
            continue
        app_id, lat, lon, distance = locations[site_id]
        application = applications[app_id]
        try:
            channel = int(row["aafq_channel"] or application["afac_channel"])
        except ValueError:
            stats["invalid_channel"] += 1
            continue
        if channel not in range(14, 37):
            stats["outside_band"] += 1
            continue
        try:
            power = erp_kw(row)
        except ValueError:
            stats["invalid_erp"] += 1
            power = None
        facility = facilities[app_id]
        # Keep DTS sites distinct. Co-channel licensees are retained separately
        # for later sharing adjudication, rather than guessed to be one emitter.
        key = (facility["facility_id"], site_id, channel)
        if key in emitters:
            stats["duplicate_frequency_rows"] += 1
            old_power = emitters[key]["erp_kw"]
            if power is not None and (old_power == "" or power > float(old_power)):
                emitters[key]["erp_kw"] = f"{power:.6g}"
            continue
        emitters[key] = {
            "schema_version": CENSUS_SCHEMA_VERSION, "rf_channel": channel,
            "callsign": facility["callsign"], "service_class": SERVICES[facility["service_code"]],
            "detectability_db": "", "distance_km": f"{distance:.1f}",
            "bearing_deg": format_bearing(bearing_deg(*center, lat, lon)),
            "frequency_tolerance": "None specified",
            "chime_ch_index": str(chime_index(channel)),
            "nominal_pilot_mhz": f"{pilot_mhz(channel):.6f}",
            "city": facility["community_served_city"],
            "state_prov": facility["community_served_state"],
            "erp_kw": "" if power is None else f"{power:.6g}",
            "evidence_status": "licensed_candidate", "latitude": lat, "longitude": lon,
            "coordinate_datum": "NAD83", "facility_id": facility["facility_id"],
            "application_id": app_id, "site_id": site_id,
            "license_filing_id": facility["license_filing_id"],
            "fcc_service": facility["service_code"], "fcc_status": facility["facility_status"],
            "source": "FCC LMS", "snapshot_date": snapshot_date,
        }
    rows = sorted(emitters.values(), key=lambda r: (r["facility_id"], r["site_id"], r["rf_channel"]))
    stats["output_rows"] = len(rows)
    stats["facilities_without_output"] = len(facilities) - len({r["facility_id"] for r in rows})
    return rows, dict(sorted(stats.items()))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="LMS table directory or combined ZIP")
    parser.add_argument("--snapshot-date", required=True, help="source snapshot date YYYY-MM-DD")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--radius-mi", type=float, default=RADIUS_MI)
    parser.add_argument("--center", type=float, nargs=2, default=DRAO, metavar=("LAT", "LON"))
    args = parser.parse_args(argv)
    # Protect both combined archives and individual source tables from overwrite.
    inputs = [args.source] if args.source.is_file() else [
        args.source / (table + suffix) for table in TABLE_FIELDS for suffix in (".dat", ".zip")]
    if any(path.resolve() == args.output.resolve() or
           (path.exists() and args.output.exists() and path.samefile(args.output))
           for path in inputs):
        parser.error("output must not overwrite an LMS input")
    try:
        rows, stats = load_fcc_lms(args.source, snapshot_date=args.snapshot_date,
                                   radius_mi=args.radius_mi, center=args.center)
    except (OSError, ValueError, BadZipFile) as exc:
        parser.error(str(exc))
    write_csv(rows, args.output, extra_fields=EXTRA_FIELDS)
    print(f"FCC LMS {args.snapshot_date}: {stats}; output -> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
