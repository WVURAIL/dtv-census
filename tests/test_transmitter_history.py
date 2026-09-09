"""Scientific guardrails for reviewed transmitter event evidence."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parents[1] / "history"
SPEC = importlib.util.spec_from_file_location("transmitter_history", PROJECT / "transmitter_history.py")
history = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(history)
SIDECAR = PROJECT / "reviewed_history_2026-09-09.json"


@pytest.fixture
def reviewed():
    return json.loads(SIDECAR.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def schedule():
    return history.schedule_records((PROJECT / "sources/ised-transition-schedule.html").read_text(encoding="utf-8"))


def test_reviewed_release_hashes_and_counts(reviewed):
    history.validate_history(reviewed, PROJECT)
    assert len(reviewed["entities"]) == 11
    assert len(reviewed["events"]) == 26
    assert reviewed["verified_rf_intervals"] == reviewed["allocation_null_intervals"] == []


def test_dt_tv_identity_counterexample():
    dt, tv = history.exact_callsign(" chan-dt-2 "), history.exact_callsign("CHAN-TV-2")
    assert dt != tv
    joined = history.join_cohort({tv: {"callsign": tv}}, [{"callsign": dt}])
    assert joined[0]["match"] == "unresolved"
    assert joined[0]["schedule"] is None
    assert joined[0]["verified_rf_interval"] is None


@pytest.mark.parametrize("bad", [None, 1, "", " "])
def test_invalid_callsign_rejected(bad):
    with pytest.raises(ValueError):
        history.exact_callsign(bad)


@pytest.mark.parametrize("bad", [None, "2018-1-1", "2018-10-01T00:00:00Z", "2018-02-30"])
def test_dates_do_not_invent_timezones_or_days(bad):
    with pytest.raises(ValueError):
        history.calendar_date(bad)


def test_all_44_exact_matches_and_bc_digital_subset(schedule):
    cohort = json.loads((PROJECT / "sources/corus-cohort-extract.json").read_text(encoding="utf-8"))["cohort"]
    joined = history.join_cohort(schedule, cohort)
    assert len(joined) == 44
    assert all(row["match"] == "exact_callsign" for row in joined)
    selected = {row["callsign"] for row in joined
                if row["schedule"]["raw"]["Province"] == "BC"
                and row["schedule"]["existing_mode"] == "D"
                and 14 <= row["schedule"]["existing_channel"] <= 36}
    assert selected == {"CITM-DT", "CHAN-DT-6", "CKTN-DT-2"}
    assert all(row["verified_rf_interval"] is None for row in joined)
    assert all(row["schedule"]["actual_transition_date"] is None for row in joined)


def test_multiplex_actors_are_not_shutdown_cohort(reviewed):
    cohort = json.loads((PROJECT / "sources/corus-cohort-extract.json").read_text(encoding="utf-8"))["cohort"]
    multiplex = {row["callsign"] for row in reviewed["entities"] if row["group"] == "multiplex"}
    assert len(multiplex) == 6
    assert not multiplex.intersection(row["callsign"] for row in cohort)


def test_taghum_independent_channel_and_bowen_planned_channel(schedule):
    assert (schedule["CKTN-DT-2"]["existing_channel"], schedule["CKTN-DT-2"]["existing_mode"]) == (23, "D")
    assert schedule["CHAN-DT-2"]["existing_channel"] == 39
    assert schedule["CHAN-DT-2"]["planned_dtv_channel"] == 28
    assert schedule["CISR-DT"]["existing_channel"] == 44
    assert schedule["CISR-DT"]["planned_dtv_channel"] == 23


def test_reference_channels_backed_by_exact_source_record(schedule, reviewed):
    fcc = json.loads((PROJECT / "sources/fcc-k20eh-notification-extract.json").read_text(encoding="utf-8"))["facility"]
    for row in reviewed["entities"]:
        if row["reference_channel_source"] == "schedule":
            assert row["reference_rf_channel"] == schedule[row["callsign"]]["existing_channel"]
        else:
            assert row["callsign"] == fcc["callsign"]
            assert row["reference_rf_channel"] == int(fcc["channel"])


def table_html(rows):
    return "<table><tr>" + "".join(f"<th>{v}</th>" for v in history.HEADER) + "</tr>" + "".join(
        "<tr>" + "".join(f"<td>{v}</td>" for v in row) + "</tr>" for row in rows) + "</table>"


def test_schedule_footnote_preserves_identity_and_planning_semantics():
    row = ["CHAN-DT-2*", "28", "39 D", "RP", "BC", "Bowen", "10", "01/01/2021", "02/01/2021", "03/01/2021", ""]
    parsed = history.schedule_records(table_html([row]))["CHAN-DT-2"]
    assert parsed["secondary_operation_footnote"]
    assert parsed["raw"]["Phase end date (MM/DD/YYYY)"] == "03/01/2021"
    assert parsed["actual_transition_date"] is None


@pytest.mark.parametrize("existing,planned", [("232 D", "23"), ("23", "23"), ("23 D", "70"), ("23 D", "unknown")])
def test_malformed_schedule_channels_rejected(existing, planned):
    row = ["CKTN-DT-2", planned, existing, "RP", "BC", "Taghum", "", "", "", "", ""]
    with pytest.raises(ValueError, match="Invalid channel"):
        history.schedule_records(table_html([row]))


def test_changed_header_and_duplicate_identity_rejected():
    with pytest.raises(ValueError, match="header"):
        history.schedule_records("<table></table>")
    row = ["CITM-DT", "21", "21 D", "RP", "BC", "100 Mile House", "", "", "", "", ""]
    with pytest.raises(ValueError, match="Duplicate schedule"):
        history.schedule_records(table_html([row, row]))
    with pytest.raises(ValueError, match="Duplicate cohort"):
        history.join_cohort({}, [{"callsign": "CITM-DT"}, {"callsign": "citm-dt"}])


@pytest.mark.parametrize("field", ["verified_rf_intervals", "allocation_null_intervals"])
def test_continuous_intervals_refused(reviewed, field):
    reviewed[field] = [{"start": "2018-10-01", "end": "2026-09-09"}]
    with pytest.raises(ValueError, match="event-only"):
        history.validate_history(reviewed, PROJECT)


@pytest.mark.parametrize("mutation,diagnostic", [
    ({"earliest_date": "2018-10-15"}, "full half-open"),
    ({"latest_date_exclusive": "2018-10-31"}, "full half-open"),
    ({"date": "2018-10-01"}, "full half-open"),
    ({"date_precision": "day"}, "full half-open"),
    ({"timezone": "UTC"}, "time zones"),
    ({"verified_rf_interval": {"state": "off"}}, "continuous RF"),
    ({"callsign": "CHAN-TV-2"}, "exact entity"),
    ({"source_id": "invented"}, "known source"),
    ({"kind": "off"}, "Unknown event"),
])
def test_event_semantic_mutations_refused(reviewed, mutation, diagnostic):
    event = next(e for e in reviewed["events"] if e["kind"] == "operator_shutdown_month")
    event.update(mutation)
    with pytest.raises(ValueError, match=diagnostic):
        history.validate_history(reviewed, PROJECT)


def test_administrative_date_cannot_become_span(reviewed):
    event = next(e for e in reviewed["events"] if e["kind"] == "administrative")
    event["earliest_date"], event["latest_date_exclusive"] = event["date"], "2026-09-09"
    with pytest.raises(ValueError, match="cannot become state spans"):
        history.validate_history(reviewed, PROJECT)


@pytest.mark.parametrize("mutation,diagnostic", [
    ({"sha256": "0" * 64}, "hash mismatch"),
    ({"file": "../requirements.txt"}, "inside the history"),
    ({"file": "/etc/hostname"}, "inside the history"),
    ({"access_kind": "verified_rf_measurement"}, "Unknown source"),
    ({"url": "file:///invented"}, "HTTPS"),
])
def test_provenance_mutations_refused(reviewed, mutation, diagnostic):
    reviewed["sources"]["schedule"].update(mutation)
    with pytest.raises(ValueError, match=diagnostic):
        history.validate_history(reviewed, PROJECT)


def test_symlink_source_cannot_escape_project(tmp_path, reviewed):
    (tmp_path / "sources").symlink_to(PROJECT / "sources", target_is_directory=True)
    with pytest.raises(ValueError, match="inside the history"):
        history.validate_history(reviewed, tmp_path)


@pytest.mark.parametrize("mutation,diagnostic", [
    ({"reference_rf_channel": True}, "Invalid reference"),
    ({"reference_rf_channel": 70}, "Invalid reference"),
    ({"reference_channel_source": "invented"}, "explicit evidence"),
    ({"unresolved": ""}, "explicit evidence"),
    ({"callsign": "chbc-dt-2"}, "canonical"),
])
def test_entity_mutations_refused(reviewed, mutation, diagnostic):
    reviewed["entities"][0].update(mutation)
    with pytest.raises(ValueError, match=diagnostic):
        history.validate_history(reviewed, PROJECT)


def test_duplicate_events_and_entities_refused(reviewed):
    bad = deepcopy(reviewed)
    bad["events"].append(deepcopy(bad["events"][0]))
    with pytest.raises(ValueError, match="Duplicate event"):
        history.validate_history(bad, PROJECT)
    reviewed["entities"].append(deepcopy(reviewed["entities"][0]))
    with pytest.raises(ValueError, match="unique"):
        history.validate_history(reviewed, PROJECT)


def test_cli_validation_does_not_plot_or_download(capsys):
    assert history.main([str(SIDECAR)]) == 0
    assert "11 exact identities, 26 events; zero RF intervals" in capsys.readouterr().out


def test_direct_workbook_reextraction_matches_reviewed_cohort():
    expected = json.loads((PROJECT / "sources/corus-cohort-extract.json").read_text(encoding="utf-8"))["cohort"]
    assert history.cohort_from_workbook(PROJECT / "sources/corus-2018-cohort.xls") == expected


def test_changed_reference_channel_refused_by_source_join(tmp_path, reviewed):
    import shutil
    shutil.copytree(PROJECT / "sources", tmp_path / "sources")
    reviewed["entities"][0]["reference_rf_channel"] = 24
    target = tmp_path / "reviewed.json"
    target.write_text(json.dumps(reviewed))
    with pytest.raises(ValueError, match="differs from the exact source record"):
        history.load_history(target)


def test_indexed_sources_preserve_access_and_rejected_lead(reviewed):
    observations = json.loads((PROJECT / "sources/web-index-observations.json").read_text(encoding="utf-8"))
    for row in observations:
        assert row["original_document_archived"] is False
        assert row["retrieved_snippets"]
        assert row["snippet_rechecked_date"] == "2026-09-09"
    rejected = next(row for row in observations if row["id"] == "crtc-2026-103-index")
    assert rejected["accepted_for_identity_history"] is False
    assert not any(event["source_id"] == rejected["id"] for event in reviewed["events"])
