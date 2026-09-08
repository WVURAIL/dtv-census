from __future__ import annotations

import csv
import math

import pytest

import verify_against_ised as verifier


def test_verification_report_and_csv_cover_match_classes_and_missing_evidence(
    workbook_file, workbook_row, ised_record, csv_file, monkeypatch, tmp_path, capsys,
):
    workbook = [
        workbook_row(**{"Call Sign": "EXACT-DT"}),
        workbook_row(**{"Call Sign": "FAR-DT", "Physical Ch(s)": 15}),
        workbook_row(**{"Call Sign": "ALIAS", "Physical Ch(s)": 16}),
        workbook_row(**{"Call Sign": "NO-POS", "Physical Ch(s)": 17,
                        "Latitude": math.nan}),
        workbook_row(**{"Call Sign": "ANALOG", "Physical Ch(s)": 18}),
        workbook_row(**{"Call Sign": "NO-TRACE", "Physical Ch(s)": 36,
                        "Latitude": math.nan}),
        workbook_row(**{"Call Sign": "CANDIDATE-TV", "Type": "analog"}),
    ]
    source = [
        ised_record(callsign="EXACT-DT"),
        ised_record(callsign="FAR-DT", frequency="479", lat="50:0:0"),
        ised_record(callsign="SITE-DT", frequency="485"),
        ised_record(callsign="NO-POS", frequency="491"),
        ised_record(callsign="ANALOG-TV", frequency="497", flag="A"),
        ised_record(callsign="NEAREST", frequency="497", lat="50:0:0"),
        ised_record(callsign="CANDIDATE-DT", frequency="503"),
        ised_record(callsign="OUTSIDE", frequency="503", lat="10:0:0"),
        *[ised_record(callsign=f"DATA{i}", kind="2") for i in range(12)],
    ]
    monkeypatch.setattr(verifier, "WORKBOOK", workbook_file(workbook))
    monkeypatch.setattr(verifier, "WS_DATA", csv_file(source))
    output = tmp_path / "matches.csv"
    assert verifier.main(["--csv", str(output)]) == 0
    report = capsys.readouterr().out
    assert "1/6 rows confirmed" in report
    assert "ANALOG on ch 18" in report
    assert "nearest same-channel digital: NEAREST" in report
    assert "no ISED trace at all" in report
    assert "within 500 mi with no on-air workbook row: 2" in report
    assert "workbook lists this station as analog/off-air" in report
    assert "OUTSIDE" not in report
    assert "... and 2 more" in report
    assert "coordinate offsets over 3 matches" in report
    with output.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        assert reader.fieldnames == [
            "wb_callsign", "channel", "city", "prov", "match", "ised_callsign",
            "offset_km", "wb_mi_drao", "ised_mi_drao", "ised_erp_dbw",
            "ised_erp_kw", "record_type"]
        pairs = list(reader)
    assert [(r["wb_callsign"], r["ised_callsign"], r["match"]) for r in pairs] == [
        ("EXACT-DT", "EXACT-DT", "callsign+position"),
        ("FAR-DT", "FAR-DT", "callsign only (position differs)"),
        ("ALIAS", "SITE-DT", "position only (callsign differs)"),
        ("NO-POS", "NO-POS", "callsign only (position differs)"),
    ]
    assert pairs[0]["offset_km"] == "0.00"
    assert pairs[0]["ised_erp_kw"] == "1.00"
    assert pairs[-1]["offset_km"] == "nan"


@pytest.mark.parametrize("export", [False, True])
def test_empty_verification(workbook_file, csv_file, monkeypatch, tmp_path, capsys,
                            export):
    monkeypatch.setattr(verifier, "WORKBOOK", workbook_file([]))
    monkeypatch.setattr(verifier, "WS_DATA", csv_file([]))
    output = tmp_path / "empty.csv"
    assert verifier.main(["--csv", str(output)] if export else []) == 0
    report = capsys.readouterr().out
    assert "0/0 rows confirmed" in report
    assert "coordinate offsets" not in report
    if export:
        assert len(output.read_text(encoding="utf-8").splitlines()) == 1
    else:
        assert not output.exists()


def test_committed_verifier_cli(run_cli, tmp_path):
    output = tmp_path / "matches.csv"
    result = run_cli("ingest/verify_against_ised.py", "--csv", output)
    assert result.returncode == 0, result.stderr
    with output.open(encoding="utf-8", newline="") as stream:
        pairs = list(csv.DictReader(stream))
    assert len(pairs) == 68
    assert sum(r["match"] == "callsign+position" for r in pairs) == 44
    assert "CHKL-DT" in {r["ised_callsign"] for r in pairs}
    assert "CH4369-DT" in result.stdout and "CH2523" in result.stdout
