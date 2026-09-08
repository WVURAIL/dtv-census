from __future__ import annotations

import csv
import math

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from census_from_xlsx import CSV_FIELDS, channels, main, reduce, write_csv
from verify_against_ised import workbook_channels


@pytest.mark.parametrize("parser", [channels, workbook_channels])
@pytest.mark.parametrize("cell, expected", [
    (None, []), (float("nan"), []), ("", []), ("VHF only", []),
    (13, []), (14, [14]), (36, [36]), (37, []), (24.0, [24]),
    ("Sh. 24; RF 9, 23, 25; 37", [24, 23, 25]),
    ("36 / 14", [36, 14]),
])
def test_channel_tokens(parser, cell, expected):
    assert parser(cell) == expected


def test_reduction_policy_expansion_and_stats(workbook_row):
    frame = pd.DataFrame([
        workbook_row(**{"Physical Ch(s)": "9; 14, 36"}),
        workbook_row(**{"Call Sign": "VHF", "Physical Ch(s)": 9}),
        *[workbook_row(**{"Type": kind})
          for kind in ["off-air", "analog", "ATSC 3.0", "unknown"]],
    ])
    before = frame.copy(deep=True)
    rows, stats = reduce(frame)
    assert [row["rf_channel"] for row in rows] == [14, 36]
    assert stats == {"n_input": 6, "n_kept": 2,
                     "dropped_by_type": {"off-air": 1, "analog": 1,
                                         "ATSC 3.0": 1, "unknown": 1},
                     "no_uhf": ["VHF"], "n_merged": 0}
    assert_frame_equal(frame, before)
    assert reduce(frame) == (rows, stats)


def test_formatting_and_missing_optional_values(workbook_row):
    row = workbook_row(**{"Call Sign": " TEST-DT ", "Class": " Relay ",
                          "City": " Town ", "State/Prov": " BC "})
    rows, _ = reduce(pd.DataFrame([row]))
    assert rows[0] == {
        "schema_version": "dtv_transmitter_census_v1", "rf_channel": 14,
        "callsign": "TEST-DT", "service_class": "Relay",
        "detectability_db": "12.35", "distance_km": "16.1",
        "bearing_deg": "90.0", "frequency_tolerance": "±1 kHz",
        "chime_ch_index": "844", "nominal_pilot_mhz": "470.309441",
        "city": "Town", "state_prov": "BC", "latitude": 49.0,
        "longitude": -119.0,
    }
    for field in ["Field Strength (dBuV/m)", "CHIME Ch Index",
                  "Nominal Pilot Freq (MHz)", "Latitude", "Longitude"]:
        row[field] = float("nan")
    missing, _ = reduce(pd.DataFrame([row]))
    for field in ["detectability_db", "chime_ch_index", "latitude", "longitude"]:
        assert missing[0][field] == ""
    # The historical workbook contract explicitly preserves missing pilot as nan.
    assert math.isnan(float(missing[0]["nominal_pilot_mhz"]))


@pytest.mark.parametrize("strengths, expected", [
    ([float("nan"), 0, -1, 5], "5.00"),
    ([10, 5, float("nan"), 10], "10.00"),
    ([float("nan")] * 4, ""),
])
def test_sharing_merges_class_and_strongest_score_but_keeps_provenance(
    workbook_row, strengths, expected,
):
    rows, stats = reduce(pd.DataFrame([
        workbook_row(**{"Call Sign": call, "Class": cls,
                        "Field Strength (dBuV/m)": strength,
                        "Frequency Tolerance": tolerance})
        for call, cls, strength, tolerance in zip(
            ["A", "B", "C", "D"], ["LPTV", "Full-power", "Relay", "Full-power"],
            strengths, ["None specified", "±1 kHz", "±1 kHz", "±1 kHz"])
    ]))
    assert len(rows) == 1
    assert rows[0]["callsign"] == "A+B+C+D"
    assert rows[0]["service_class"] == "Full-power"
    assert rows[0]["detectability_db"] == expected
    assert rows[0]["frequency_tolerance"] == "None specified"
    assert stats["n_merged"] == 3


@pytest.mark.parametrize("field, value", [
    ("Physical Ch(s)", 15), ("City", "Other Town"), ("State/Prov", "AB"),
    ("Distance to DRAO (mi)", 20), ("Bearing from DRAO (deg, True)", 180),
])
def test_distinct_emitters_are_not_merged(workbook_row, field, value):
    rows, stats = reduce(pd.DataFrame([
        workbook_row(), workbook_row(**{field: value, "Call Sign": "OTHER"})]))
    assert len(rows) == 2
    assert stats["n_merged"] == 0


def test_empty_and_fully_filtered_workbooks(workbook_row):
    for frame in [pd.DataFrame(columns=workbook_row().keys()),
                  pd.DataFrame([workbook_row(**{"Type": "off-air"})])]:
        rows, stats = reduce(frame)
        assert rows == []
        assert stats["n_kept"] == stats["n_merged"] == 0
        assert stats["no_uhf"] == []


@pytest.mark.parametrize("angle, expected", [(359.96, "0.0"), (360, "0.0"),
                                            (359.94, "359.9"), (-0.01, "0.0")])
def test_rounded_bearing_stays_in_schema_range(workbook_row, angle, expected):
    rows, _ = reduce(pd.DataFrame([
        workbook_row(**{"Bearing from DRAO (deg, True)": angle})]))
    assert rows[0]["bearing_deg"] == expected


def test_csv_round_trip_schema_quoting_extras_and_empty_output(tmp_path):
    path = tmp_path / "out.csv"
    row = {"callsign": "A+B", "city": 'Town, "Québec"\nNorth',
           "frequency_tolerance": "±1 kHz", "erp_kw": "0.001",
           "latitude": 49, "unexpected": "ignored"}
    write_csv([row], path, extra_fields=["erp_kw"])
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        assert reader.fieldnames == CSV_FIELDS + ["erp_kw"]
        assert list(reader) == [
            {field: row.get(field, "") for field in CSV_FIELDS + ["erp_kw"]}]
    write_csv([], path)
    assert path.read_text(encoding="utf-8") == ",".join(CSV_FIELDS) + "\n"


def test_reduction_cli_reports_filtering(workbook_file, workbook_row, tmp_path,
                                         run_cli):
    source = workbook_file([
        workbook_row(), workbook_row(**{"Physical Ch(s)": 9}),
        workbook_row(**{"Type": "analog"}),
    ])
    result = run_cli("census/census_from_xlsx.py", source, tmp_path / "out.csv")
    assert result.returncode == 0, result.stderr
    assert "input rows: 3; on-air kept: 2" in result.stdout
    assert "no UHF 14..36" in result.stdout
    assert "output rows (one per physical emitter-channel): 1" in result.stdout


def test_reduction_cli_without_skipped_channels(workbook_file, workbook_row,
                                               tmp_path, capsys):
    assert main([workbook_file([workbook_row()]), tmp_path / "out.csv"]) == 0
    assert "no UHF" not in capsys.readouterr().out
