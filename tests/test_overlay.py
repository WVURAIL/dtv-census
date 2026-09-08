from __future__ import annotations

import csv
import math

import pytest

import apply_ised_overlay as overlay
import verify_against_ised as verifier
from census_from_xlsx import CSV_FIELDS


@pytest.fixture
def run_overlay(workbook_file, csv_file, monkeypatch, tmp_path, capsys):
    def run(workbook_rows, ised_rows):
        monkeypatch.setattr(overlay, "WORKBOOK", workbook_file(workbook_rows))
        monkeypatch.setattr(verifier, "WS_DATA", csv_file(ised_rows))
        destination = tmp_path / "census.csv"
        assert overlay.main(["--output", str(destination)]) == 0
        with destination.open(encoding="utf-8", newline="") as stream:
            reader = csv.DictReader(stream)
            assert reader.fieldnames == CSV_FIELDS + ["erp_kw", "evidence_status"]
            rows = list(reader)
        return rows, capsys.readouterr().out
    return run


@pytest.mark.parametrize("end, expected", [
    ((1, 0), 0), ((0, 1), 90), ((-1, 0), 180), ((0, -1), 270), ((0, 0), 0),
])
def test_cardinal_bearings(end, expected):
    assert overlay.bearing_deg(0, 0, *end) == pytest.approx(expected)


@pytest.mark.parametrize("channel, frequency, index", [
    (14, 470.309441, 844), (30, 566.309441, 598), (36, 602.309441, 506),
])
def test_spectral_coordinates(channel, frequency, index):
    assert overlay.pilot_mhz(channel) == pytest.approx(frequency)
    assert overlay.chime_index(channel) == index


def test_all_uhf_pilots_progress_by_one_channel():
    pilots = [overlay.pilot_mhz(ch) for ch in range(14, 37)]
    assert all(b - a == pytest.approx(6) for a, b in zip(pilots, pilots[1:]))
    assert all(0 <= overlay.chime_index(ch) < 1024 for ch in range(14, 37))


@pytest.mark.parametrize("old_distance, expected_shift", [
    ("200", 200 - 111.1950802335), ("", 0), (None, 0),
])
@pytest.mark.parametrize("erp, expected", [(0, "0.001"), (30, "1.000"),
                                          (60, "1000.000"), (math.nan, "")])
def test_apply_site_geometry_erp_units_and_preserved_fields(
    monkeypatch, old_distance, expected_shift, erp, expected,
):
    monkeypatch.setattr(overlay, "DRAO", (0, 0))
    row = {"callsign": "TEST", "detectability_db": "42.00"}
    if old_distance is not None:
        row["distance_km"] = old_distance
    shift = overlay.apply_site(row, {"lat": 0, "lon": 1, "erp_dbw": erp})
    assert shift == pytest.approx(expected_shift)
    assert row == {"callsign": "TEST", "detectability_db": "42.00",
                   "distance_km": "111.2", "bearing_deg": "90.0", "erp_kw": expected}


def test_us_pass_through_and_canadian_match_precedence(run_overlay, workbook_row,
                                                      ised_record):
    workbook = [
        workbook_row(**{"State/Prov": "WA", "Call Sign": "US"}),
        workbook_row(**{"Call Sign": "MATCH-DT", "City": "Distant city"}),
        workbook_row(**{"Call Sign": "SHARED", "Physical Ch(s)": 15}),
        workbook_row(**{"Call Sign": "PARTNER-DT", "Physical Ch(s)": 15,
                        "Class": "Full-power"}),
    ]
    rows, report = run_overlay(workbook, [
        # Same-channel nearby station must not override the callsign match.
        ised_record(callsign="NEAR-DT"),
        ised_record(callsign="MATCH-DT", lat="50:0:0", erp="40"),
        ised_record(callsign="PARTNER-DT", frequency="479", erp="30"),
    ])
    by_call = {r["callsign"]: r for r in rows}
    assert by_call["US"]["evidence_status"] == "reported_on_air_unverified"
    assert by_call["US"]["erp_kw"] == ""
    assert by_call["US"]["distance_km"] == "16.1"
    assert by_call["US"]["bearing_deg"] == "90.0"
    assert by_call["MATCH-DT"]["erp_kw"] == "10.000"
    assert by_call["MATCH-DT"]["city"] == "Distant city"
    assert by_call["MATCH-DT"]["evidence_status"] == "reported_on_air_licensed"
    assert by_call["SHARED+PARTNER-DT"]["service_class"] == "Full-power"
    assert by_call["SHARED+PARTNER-DT"]["evidence_status"] == "reported_on_air_licensed"
    assert by_call["NEAR-DT"]["evidence_status"] == "licensed_candidate"
    assert len(rows) == 4
    assert "MOVE MATCH-DT" in report
    assert "2 Canadian rows matched" in report
    assert "1 share-merges" in report


@pytest.mark.parametrize("distance, matched", [(9.99, True), (10, True), (10.01, False)])
def test_position_match_tolerance_and_channel(run_overlay, workbook_row, ised_record,
                                             monkeypatch, distance, matched):
    monkeypatch.setattr(overlay, "haversine_km", lambda *args: distance)
    rows, report = run_overlay([workbook_row(**{"Call Sign": "ALIAS"})], [
        ised_record(callsign="WRONG-CHANNEL", frequency="479"),
        ised_record(callsign="SITE-DT"),
    ])
    by_call = {r["callsign"]: r for r in rows}
    assert ("ALIAS" in by_call) is matched
    if matched:
        assert by_call["ALIAS"]["rf_channel"] == "14"
        assert by_call["ALIAS"]["evidence_status"] == "reported_on_air_licensed"
        assert "SITE-DT" not in by_call
    else:
        assert "DROP ALIAS" in report


@pytest.mark.parametrize("missing", ["Latitude", "Longitude"])
@pytest.mark.parametrize("same_call", [False, True])
def test_missing_position_allows_callsign_match_but_not_position_fallback(
    run_overlay, workbook_row, ised_record, missing, same_call,
):
    rows, report = run_overlay([
        workbook_row(**{missing: math.nan, "Call Sign": "WORKBOOK-DT"})],
        [ised_record(callsign="WORKBOOK-DT" if same_call else "OTHER-DT")])
    assert len(rows) == 1
    assert rows[0]["evidence_status"] == (
        "reported_on_air_licensed" if same_call else "licensed_candidate")
    assert ("DROP WORKBOOK-DT" in report) is (not same_call)


def test_promotions_additions_dedup_and_evidence(run_overlay, workbook_row, ised_record):
    rows, report = run_overlay([
        workbook_row(**{"Call Sign": "LIVE-DT"}),
        workbook_row(**{"Call Sign": "LIVE-TV", "Type": "analog"}),
        workbook_row(**{"Call Sign": "PROMO-TV", "Type": "analog",
                        "Field Strength (dBuV/m)": math.nan}),
        workbook_row(**{"Call Sign": "PROMO-TV", "Type": "analog"}),
        workbook_row(**{"Call Sign": "OFF-DT", "Type": "off-air"}),
        workbook_row(**{"Call Sign": "ANALOG-TV", "Type": "analog"}),
    ], [
        ised_record(callsign="LIVE-DT"),
        ised_record(callsign="PROMO-DT", frequency="479", kind="5"),
        ised_record(callsign="PROMO-DT", frequency="485", kind="5"),
        ised_record(callsign="OFF-DT", frequency="491", kind="4", erp=""),
        ised_record(callsign="ABSENT-DT", frequency="497"),
        ised_record(callsign="ANALOG-TV", flag="A"),
        ised_record(callsign="DATA", kind="2"),
        ised_record(callsign="FAR-DT", lat="10:0:0"),
    ])
    assert [(r["callsign"], r["rf_channel"]) for r in rows] == [
        ("LIVE-DT", "14"), ("PROMO-TV", "15"), ("PROMO-TV", "16"),
        ("OFF-DT", "17"), ("ABSENT-DT", "18")]
    assert rows[0]["evidence_status"] == "reported_on_air_licensed"
    assert all(r["evidence_status"] == "licensed_candidate" for r in rows[1:])
    assert rows[1]["detectability_db"] == rows[2]["detectability_db"] == ""
    assert rows[1]["nominal_pilot_mhz"] == "476.309441"
    assert rows[1]["chime_ch_index"] == "829"
    assert rows[3]["service_class"] == "LPA"
    assert rows[3]["erp_kw"] == ""
    assert rows[4]["service_class"] == "Full-power"
    assert rows[4]["frequency_tolerance"] == "None specified"
    assert "2 promoted, 2 added" in report


def test_promoted_field_strength_is_preserved(run_overlay, workbook_row, ised_record):
    rows, _ = run_overlay([workbook_row(**{"Type": "analog"})], [ised_record()])
    assert rows[0]["detectability_db"] == "12.35"


def test_empty_inputs_produce_header_and_zero_counts(run_overlay):
    rows, report = run_overlay([], [])
    assert rows == []
    assert "final: 0 emitter-channel rows" in report


def test_radius_boundary_and_distance_order(run_overlay, ised_record, csv_file,
                                            monkeypatch):
    monkeypatch.setattr(verifier, "WS_DATA", csv_file([
        ised_record(callsign=f"SITE{i}") for i in range(4)]))
    stations, analog, other, raw = verifier.load_ised()
    for station, miles in zip(stations, [500.001, 500, 499.999, 1]):
        station["drao_mi"] = miles
    monkeypatch.setattr(overlay, "load_ised", lambda: (stations, analog, other, raw))
    rows, _ = run_overlay([], [])
    assert [r["callsign"] for r in rows] == ["SITE3", "SITE2", "SITE1"]


def test_negligible_site_change_is_not_reported_as_move(run_overlay, workbook_row,
                                                      ised_record):
    miles = verifier.haversine_km(*verifier.DRAO, 49, -119) / 1.609344
    _, report = run_overlay([
        workbook_row(**{"Distance to DRAO (mi)": miles})], [ised_record()])
    assert "MOVE " not in report
    assert "0 moved > 1 km" in report


def test_just_west_of_north_does_not_round_to_360(monkeypatch):
    monkeypatch.setattr(overlay, "DRAO", (0, 0))
    row = {}
    overlay.apply_site(row, {"lat": 1, "lon": -0.000001, "erp_dbw": 30})
    assert row["bearing_deg"] == "0.0"
