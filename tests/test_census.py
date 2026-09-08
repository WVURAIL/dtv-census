from __future__ import annotations

import csv
import math
import subprocess
import sys
from collections import Counter
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "census"))

from census_from_xlsx import (  # noqa: E402
    CENSUS_SCHEMA_VERSION,
    CSV_FIELDS,
    channels,
    write_csv,
)


def test_channel_token_expansion_is_limited_to_uhf_dtv() -> None:
    assert channels("Sh. 24; RF 9, 23, 25; 37") == [24, 23, 25]


def test_write_csv_is_utf8_with_lf_line_endings(tmp_path: Path) -> None:
    output = tmp_path / "census.csv"
    row = {
        "schema_version": CENSUS_SCHEMA_VERSION,
        "rf_channel": 30,
        "callsign": "CHKL-1",
        "service_class": "Relay",
        "detectability_db": "79.31",
        "distance_km": "37.8",
        "bearing_deg": "5.6",
        "frequency_tolerance": "±1 kHz",
        "chime_ch_index": "598",
        "nominal_pilot_mhz": "566.309441",
        "city": "Penticton",
        "state_prov": "BC",
    }
    write_csv([row], output)
    payload = output.read_bytes()
    assert b"\xc2\xb11 kHz" in payload
    assert b"\r\n" not in payload


def test_committed_census_has_explicit_evidence_envelope() -> None:
    with (REPO / "census" / "census.csv").open(
        encoding="utf-8", newline=""
    ) as stream:
        rows = list(csv.DictReader(stream))

    assert len(rows) == 499
    assert {row["schema_version"] for row in rows} == {CENSUS_SCHEMA_VERSION}
    assert all(14 <= int(row["rf_channel"]) <= 36 for row in rows)
    assert all(row["evidence_status"] for row in rows)
    assert Counter(row["evidence_status"] for row in rows) == {
        "reported_on_air_unverified": 421,
        "reported_on_air_licensed": 67,
        "licensed_candidate": 11,
    }


def test_full_regeneration_is_byte_exact(tmp_path: Path) -> None:
    regenerated = tmp_path / "census.csv"
    subprocess.run(
        [
            sys.executable,
            str(REPO / "ingest" / "apply_ised_overlay.py"),
            "--output",
            str(regenerated),
        ],
        check=True,
        capture_output=True,
        timeout=60,
    )
    assert regenerated.read_bytes() == (REPO / "census" / "census.csv").read_bytes()


def test_committed_numeric_schema_and_evidence_consistency() -> None:
    with (REPO / "census" / "census.csv").open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        assert reader.fieldnames == CSV_FIELDS + ["erp_kw", "evidence_status"]
        rows = list(reader)
    for row in rows:
        assert None not in row and None not in row.values(), row
        assert row["callsign"] and row["service_class"] and row["city"], row
        assert len(row["state_prov"]) == 2, row
        assert math.isfinite(float(row["distance_km"])), row
        assert float(row["distance_km"]) >= 0, row
        assert 0 <= float(row["bearing_deg"]) < 360, row
        for optional in ("detectability_db", "erp_kw"):
            assert not row[optional] or math.isfinite(float(row[optional])), row
        if row["chime_ch_index"]:
            assert 0 <= int(row["chime_ch_index"]) < 1024, row
        if row["evidence_status"] == "reported_on_air_unverified":
            assert row["state_prov"] not in {"BC", "AB", "SK", "YT"}, row
            assert row["erp_kw"] == "", row
        else:
            assert row["state_prov"] in {"BC", "AB", "SK", "YT"}, row
            assert float(row["erp_kw"]) > 0, row


def test_us_workbook_fields_survive_overlay_without_changes():
    import pandas as pd
    from census_from_xlsx import reduce

    reduced, _ = reduce(pd.read_excel(REPO / "census" / "TV_Stations_UHF_within500mi_DRAO.xlsx"))
    expected = [{field: str(row[field]) for field in CSV_FIELDS}
                for row in reduced if row["state_prov"] not in {"BC", "AB", "SK", "YT"}]
    with (REPO / "census" / "census.csv").open(encoding="utf-8", newline="") as stream:
        actual = [{field: row[field] for field in CSV_FIELDS} for row in csv.DictReader(stream)
                  if row["evidence_status"] == "reported_on_air_unverified"]
    assert actual == expected
