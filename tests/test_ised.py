from __future__ import annotations

import itertools
import math

import pytest

import verify_against_ised as verifier


@pytest.mark.parametrize("value, expected", [
    ("CHKL-DT-1AX1", ("CHKL-1", True)),
    ("CHKL-1", ("CHKL-1", False)),
    ("CBUT-DT-AX1", ("CBUT", True)),
    ("CFEG-TV", ("CFEG", False)), ("CFEG-DT", ("CFEG", False)),
    (" cbUt-dt ", ("CBUT", False)), ("CHKL-DT-12", ("CHKL-12", False)),
    ("TEST-AX", ("TEST", True)), ("AXIS-DT", ("AXIS", False)),
    ("KDTX", ("KDTX", False)), ("", ("", False)),
])
def test_callsign_canonicalization(value, expected):
    assert verifier.canon_callsign(value) == expected


@pytest.mark.parametrize("value, expected", [
    ("49:30:0", 49.5), ("119:37:26.04", 119.6239), ("0:0:0", 0),
    (" 49 : 30 : 30 ", 49.5083333333),
])
def test_dms_conversion(value, expected):
    assert verifier.dms_to_deg(value) == pytest.approx(expected)


@pytest.mark.parametrize("value", ["", "49:30", "49:30:0:0", "x:0:0"])
def test_malformed_dms_raises(value):
    with pytest.raises(ValueError):
        verifier.dms_to_deg(value)


@pytest.mark.parametrize("start, end, expected", [
    ((49, -119), (49, -119), 0),
    ((0, 0), (0, 1), 111.1950802335),
    ((0, 0), (90, 0), math.pi * 6371.0088 / 2),
    ((0, 179), (0, -179), 222.390160467),
    ((0, 0), (0, 180), math.pi * 6371.0088),
])
def test_geodesic_known_distances_and_symmetry(start, end, expected):
    assert verifier.haversine_km(*start, *end) == pytest.approx(expected, abs=1e-6)
    assert verifier.haversine_km(*end, *start) == pytest.approx(expected, abs=1e-6)


def test_antipodal_roundoff_stays_in_domain():
    for latitude in range(-89, 90):
        assert verifier.haversine_km(latitude, -119.6239, -latitude, 60.3761) == (
            pytest.approx(math.pi * 6371.0088, abs=0.001))


def test_unknown_position_is_not_mistaken_for_zero_distance():
    assert math.isnan(verifier.haversine_km(math.nan, 0, 0, 0))


def test_ised_source_mapping_and_classification(ised_record, csv_file, monkeypatch):
    source = csv_file([
        ised_record(name=" Québec ", lat="49:30:0", lon="119:30:0"),
        *[ised_record(callsign=f"KIND{kind}", kind=kind)
          for kind in ["2", "3", "4", "5", "99"]],
        ised_record(callsign="ANALOG-TV", flag="A", frequency="479"),
        ised_record(callsign="ANALOG-TV", flag="A", frequency="485"),
    ])
    monkeypatch.setattr(verifier, "WS_DATA", source)
    stations, analog, other, raw = verifier.load_ised()
    assert raw == 6
    assert [r["record_type"] for r in stations] == ["TV", "LPA", "LPTV"]
    assert [r["record_type"] for r in other] == ["RRBS", "non-protected", "99"]
    assert analog == {"ANALOG": {15, 16}}
    station = stations[0]
    assert station == {
        "callsign": "TEST-DT", "base": "TEST", "aux": False, "channel": 14,
        "name": "Québec", "lat": 49.5, "lon": -119.5, "prov": "BC",
        "erp_dbw": 30.0, "record_type": "TV", "n_records": 1,
        "drao_mi": pytest.approx(13.576673, abs=0.000001),
    }


@pytest.mark.parametrize("frequency, channel", [
    ("469.999", None), ("470", 14), ("475.999", 14), ("476", 15),
    ("602", 36), ("607.999", 36), ("608", None),
    ("", None), ("bad", None), ("nan", None), ("inf", None),
])
def test_ised_frequency_edges(ised_record, csv_file, monkeypatch, frequency, channel):
    monkeypatch.setattr(verifier, "WS_DATA", csv_file([ised_record(frequency=frequency)]))
    stations, _, _, raw = verifier.load_ised()
    assert [s["channel"] for s in stations] == ([] if channel is None else [channel])
    assert raw == (channel is not None)


@pytest.mark.parametrize("lat, lon", [
    ("", "119:0:0"), ("49:0:0", "bad"), ("nan:0:0", "119:0:0"),
    ("inf:0:0", "119:0:0"), ("91:0:0", "119:0:0"),
    ("49:0:0", "181:0:0"), ("49:60:0", "119:0:0"),
    ("49:0:60", "119:0:0"),
])
def test_ised_skips_unusable_coordinates(ised_record, csv_file, monkeypatch, lat, lon):
    monkeypatch.setattr(verifier, "WS_DATA", csv_file([ised_record(lat=lat, lon=lon)]))
    assert verifier.load_ised() == ([], {}, [], 0)


@pytest.mark.parametrize("erp", ["bad", "", "nan", "inf", "-inf"])
def test_empty_short_records_and_missing_erp(ised_record, csv_file, monkeypatch, erp):
    monkeypatch.setattr(verifier, "WS_DATA", csv_file([[], ["short"],
                                                     ised_record(erp=erp)]))
    stations, _, _, raw = verifier.load_ised()
    assert raw == 1
    assert math.isnan(stations[0]["erp_dbw"])


@pytest.mark.parametrize("order", list(itertools.permutations(range(3))))
def test_dedup_selects_main_highest_known_erp_and_matching_metadata(
    ised_record, csv_file, monkeypatch, order,
):
    records = [ised_record(callsign="TEST-DT-AX1", erp="60", name="Aux",
                           lat="51:0:0", kind="5"),
               ised_record(erp="", name="Unknown power", lat="50:0:0"),
               ised_record(erp="30", name="Main site", lat="49:0:0")]
    monkeypatch.setattr(verifier, "WS_DATA", csv_file([records[i] for i in order]))
    stations, analog, other, raw = verifier.load_ised()
    assert raw == 3
    assert analog == {} and other == []
    assert len(stations) == 1
    station = stations[0]
    assert station["n_records"] == 3
    assert station["callsign"] == "TEST-DT"
    assert station["aux"] is False
    assert station["erp_dbw"] == 30
    assert station["name"] == "Main site"
    assert station["record_type"] == "TV"
    assert station["lat"] == 49
    assert station["drao_mi"] == pytest.approx(
        verifier.haversine_km(*verifier.DRAO, 49, -119) / 1.609344)


@pytest.mark.parametrize("order", [(20, 40), (40, 20)])
@pytest.mark.parametrize("suffix", ["", "-AX1"])
def test_repeated_authorizations_keep_highest_erp(ised_record, csv_file, monkeypatch,
                                                order, suffix):
    monkeypatch.setattr(verifier, "WS_DATA", csv_file([
        ised_record(callsign="TEST-DT" + suffix, erp=str(erp)) for erp in order]))
    stations, _, _, raw = verifier.load_ised()
    assert raw == stations[0]["n_records"] == 2
    assert stations[0]["erp_dbw"] == 40


def test_same_callsign_on_different_channels_remains_distinct(ised_record, csv_file,
                                                            monkeypatch):
    monkeypatch.setattr(verifier, "WS_DATA", csv_file([
        ised_record(frequency="473"), ised_record(frequency="479")]))
    stations, _, _, _ = verifier.load_ised()
    assert [s["channel"] for s in stations] == [14, 15]


def test_workbook_loading_scope_status_channel_expansion_and_partial_position(
    workbook_file, workbook_row, monkeypatch,
):
    rows = [workbook_row(**{"State/Prov": prov, "Call Sign": f"{prov}-DT",
                            "Physical Ch(s)": "9; 14, 36", "Type": "analog"})
            for prov in ["BC", "AB", "SK", "YT", "WA"]]
    rows += [workbook_row(**{"Longitude": float("nan"), "Call Sign": "NO-LON"}),
             workbook_row(**{"Latitude": float("nan"), "Call Sign": "NO-LAT"})]
    monkeypatch.setattr(verifier, "WORKBOOK", workbook_file(rows))
    loaded = verifier.load_workbook()
    assert len(loaded) == 10
    assert {r["prov"] for r in loaded} == {"BC", "AB", "SK", "YT"}
    assert [r["channel"] for r in loaded[:8]] == [14, 36] * 4
    assert all(r["type"] == "analog" for r in loaded[:8])
    assert loaded[0]["base"] == "BC"
    assert loaded[0]["wb_mi"] == 10
    for row in loaded[-2:]:
        assert row["lat"] is None and row["lon"] is None
