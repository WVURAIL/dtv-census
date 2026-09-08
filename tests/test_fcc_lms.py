from __future__ import annotations

import copy
import csv
import io
import math
from pathlib import Path
from zipfile import ZipFile

import pytest

import load_fcc_lms as fcc

FIXTURE = Path(__file__).parent / "fixtures" / "fcc_lms"
SNAPSHOT = "2026-09-08"


@pytest.fixture
def lms_tables():
    tables = {}
    for path in FIXTURE.glob("*.dat"):
        with path.open(encoding="utf-8", newline="") as stream:
            tables[path.stem] = [
                {k: v for k, v in row.items() if k not in ("^", "")}
                for row in csv.DictReader(stream, delimiter="|", quoting=csv.QUOTE_NONE)]
    return tables


@pytest.fixture
def save_lms(tmp_path):
    def save(tables, layout="dat", trailer=True):
        directory = tmp_path / "lms"
        directory.mkdir(exist_ok=True)
        archive_path = tmp_path / "LMS_Dump.zip"
        for name, rows in tables.items():
            # Use the source header even when testing an empty table.
            header = (FIXTURE / f"{name}.dat").read_text(encoding="utf-8").splitlines()[0]
            fields = header.split("|")[:-2]
            output = io.StringIO(newline="")
            writer = csv.writer(output, delimiter="|", quoting=csv.QUOTE_NONE,
                                lineterminator="\n")
            tail = ["^", ""] if trailer else []
            writer.writerow(fields + tail)
            for row in rows:
                writer.writerow([row.get(field, "") for field in fields] + tail)
            payload = output.getvalue()
            if layout == "dat":
                (directory / f"{name}.dat").write_text(payload, encoding="utf-8")
            else:
                path = directory / f"{name}.zip" if layout == "zips" else archive_path
                with ZipFile(path, "a") as archive:
                    archive.writestr(f"{name}.dat", payload)
        return archive_path if layout == "combined" else directory
    return save


def test_official_krem_fixture_has_known_channel_site_power_and_provenance():
    rows, stats = fcc.load_fcc_lms(FIXTURE, snapshot_date=SNAPSHOT)
    assert len(rows) == 1
    row = rows[0]
    assert row["callsign"] == "KREM"
    assert row["rf_channel"] == 20  # Physical 20, not virtual channel 2.
    assert row["erp_kw"] == "810"  # FCC reports kW already; no dBW conversion.
    assert row["latitude"] == pytest.approx(47 + 35 / 60 + 41 / 3600)
    assert row["longitude"] == pytest.approx(-(117 + 17 / 60 + 57 / 3600))
    assert row["coordinate_datum"] == "NAD83"
    assert row["facility_id"] == "34868"
    assert row["application_id"] == "25076f9190a2e2810190b80220660e8e"
    assert row["nominal_pilot_mhz"] == "506.309441"
    assert row["evidence_status"] == "licensed_candidate"
    assert row["source"] == "FCC LMS" and row["snapshot_date"] == SNAPSHOT
    assert stats["output_rows"] == 1 and stats["facilities_without_output"] == 0


@pytest.mark.parametrize("layout", ["dat", "zips", "combined"])
@pytest.mark.parametrize("trailer", [False, True])
def test_native_table_packaging(lms_tables, save_lms, layout, trailer):
    source = save_lms(lms_tables, layout, trailer)
    assert fcc.load_fcc_lms(source, snapshot_date=SNAPSHOT) == fcc.load_fcc_lms(
        FIXTURE, snapshot_date=SNAPSHOT)


@pytest.mark.parametrize("table, field, value", [
    ("facility", "active_ind", "N"), ("facility", "service_code", "TV"),
    ("facility", "service_code", "FM"), ("facility", "service_code", "DTX"),
    ("facility", "facility_status", "LICSL"), ("facility", "facility_status", "LICAN"),
    ("facility", "facility_status", "CPAPP"), ("facility", "facility_status", "LICSU"),
    ("facility", "atsc3_ind", "Y"), ("facility", "callsign", ""),
    ("facility", "latest_filing_version_id", ""), ("facility", "facility_id", ""),
    ("facility", "license_filing_id", ""),
    ("license_filing_version", "active_ind", "N"),
    ("license_filing_version", "auth_type_code", "C"),
    ("license_filing_version", "current_status_code", "PEN"),
    ("license_filing_version", "service_code", "FM"),
    ("license_filing_version", "license_filing_id", "different"),
    ("application_facility", "active_ind", "N"),
    ("application_facility", "country_code", "CA"),
    ("application_facility", "country_code", "MX"),
    ("application_facility", "atsc3_ind", "Y"),
    ("application_facility", "afac_facility_id", "wrong-facility"),
    ("app_location", "aloc_active_ind", "N"),
    ("app_location", "aloc_dts_reference_location_ind", "Y"),
    ("app_location", "aloc_lat_deg", "nan"),
    ("app_location", "aloc_loc_record_id", ""),
    ("app_antenna", "aant_active_ind", "N"),
    ("app_antenna", "aant_antenna_record_id", ""),
    ("app_antenna_frequency", "aafq_active_ind", "N"),
    ("app_antenna_frequency", "aafq_channel", "bad"),
    ("app_antenna_frequency", "aafq_channel", "13"),
    ("app_antenna_frequency", "aafq_channel", "37"),
])
def test_selection_and_invalid_record_exclusions(lms_tables, save_lms, table, field, value):
    lms_tables[table][0][field] = value
    rows, _ = fcc.load_fcc_lms(save_lms(lms_tables), snapshot_date=SNAPSHOT)
    assert rows == []


@pytest.mark.parametrize("table", list(fcc.TABLE_FIELDS))
def test_missing_join_never_falls_back_to_unrelated_record(lms_tables, save_lms, table):
    lms_tables[table] = []
    rows, _ = fcc.load_fcc_lms(save_lms(lms_tables), snapshot_date=SNAPSHOT)
    assert rows == []


def test_current_licence_pointer_wins_over_newer_pending_application(lms_tables, save_lms):
    pending = copy.deepcopy(lms_tables["license_filing_version"][0])
    pending.update(filing_version_id="newer-pending", current_status_code="PEN",
                   auth_type_code="C", status_date="2026-09-08")
    lms_tables["license_filing_version"].append(pending)
    rows, _ = fcc.load_fcc_lms(save_lms(lms_tables), snapshot_date=SNAPSHOT)
    assert len(rows) == 1
    assert rows[0]["application_id"] != "newer-pending"


def test_dts_sites_and_channels_remain_distinct_duplicates_keep_max_power(lms_tables, save_lms):
    lms_tables["facility"][0]["service_code"] = "DTS"
    site = dict(lms_tables["app_location"][0], aloc_loc_record_id="second-site",
                aloc_lat_ss="42.0")
    lms_tables["app_location"].append(site)
    lms_tables["app_antenna"].append(dict(lms_tables["app_antenna"][0],
        aant_aloc_loc_record_id="second-site", aant_antenna_record_id="second-antenna"))
    frequency = lms_tables["app_antenna_frequency"][0]
    lms_tables["app_antenna_frequency"] += [
        dict(frequency, aafq_aant_antenna_record_id="second-antenna"),
        dict(frequency, aafq_channel="21"),
        dict(frequency, aafq_power_erp_kw="900"),
        dict(frequency, aafq_power_erp_kw="5"),
        dict(frequency, aafq_power_erp_kw=""),
    ]
    rows, stats = fcc.load_fcc_lms(save_lms(lms_tables), snapshot_date=SNAPSHOT)
    assert len(rows) == 3
    assert len({r["site_id"] for r in rows}) == 2
    assert {(r["rf_channel"], r["erp_kw"]) for r in rows} == {
        (20, "900"), (20, "810"), (21, "810")}
    assert stats["duplicate_frequency_rows"] == 3


@pytest.mark.parametrize("power", ["bad", "-1", "nan", "inf"])
def test_invalid_optional_power_is_blank_and_diagnosed(lms_tables, save_lms, power):
    lms_tables["app_antenna_frequency"][0]["aafq_power_erp_kw"] = power
    rows, stats = fcc.load_fcc_lms(save_lms(lms_tables), snapshot_date=SNAPSHOT)
    assert rows[0]["erp_kw"] == ""
    assert stats["invalid_erp"] == 1


@pytest.mark.parametrize("values, expected", [
    (("0", "10", "20", "30"), 0), (("", "10", "20", "30"), 10),
    (("", "", "20", "30"), 30), (("", "", "", ""), None),
    (("", "", "0.015", ""), 0.015),
])
def test_power_units_precedence_and_polarizations(values, expected):
    row = dict(zip(["aafq_power_erp_kw", "aafq_max_erp_kw",
                    "aafq_horiz_erp_kw", "aafq_vert_erp_kw"], values))
    assert fcc.erp_kw(row) == expected


def test_invalid_polarization_power_rejected():
    with pytest.raises(ValueError, match="ERP"):
        fcc.erp_kw({"aafq_power_erp_kw": "", "aafq_max_erp_kw": "",
                    "aafq_horiz_erp_kw": "inf", "aafq_vert_erp_kw": ""})


@pytest.mark.parametrize("axis, direction, degrees, expected", [
    ("lat", "N", "47", 47), ("lat", "S", "47", -47),
    ("long", "E", "117", 117), ("long", "w", "117", -117),
    ("lat", "N", "90", 90), ("long", "W", "180", -180),
])
def test_hemispheres_and_coordinate_limits(axis, direction, degrees, expected):
    row = {f"aloc_{axis}_{part}": value for part, value in
           zip(["deg", "mm", "ss", "dir"], [degrees, "0", "0", direction])}
    assert fcc.coordinate(row, axis) == expected


@pytest.mark.parametrize("direction, degrees", [("", "47"), ("E", "47"),
                                               ("N", "91"), ("N", "inf")])
def test_invalid_coordinates(direction, degrees):
    with pytest.raises(ValueError):
        fcc.coordinate({"aloc_lat_deg": degrees, "aloc_lat_mm": "0",
                         "aloc_lat_ss": "0", "aloc_lat_dir": direction}, "lat")


def test_radius_filter_and_inclusive_center(lms_tables, save_lms):
    source = save_lms(lms_tables)
    assert fcc.load_fcc_lms(source, snapshot_date=SNAPSHOT, radius_mi=1)[0] == []
    center = (47 + 35 / 60 + 41 / 3600, -(117 + 17 / 60 + 57 / 3600))
    rows, _ = fcc.load_fcc_lms(source, snapshot_date=SNAPSHOT, radius_mi=0, center=center)
    assert len(rows) == 1
    assert rows[0]["distance_km"] == "0.0"


@pytest.mark.parametrize("kwargs", [
    {"snapshot_date": "yesterday"}, {"snapshot_date": "2026-02-30"},
    {"radius_mi": -1}, {"radius_mi": math.nan}, {"radius_mi": math.inf},
    {"center": (91, 0)}, {"center": (0, 181)}, {"center": (math.nan, 0)},
    {"center": (0,)},
])
def test_invalid_query_fails_before_loading(kwargs):
    options = {"snapshot_date": SNAPSHOT, **kwargs}
    with pytest.raises(ValueError):
        fcc.load_fcc_lms("nonexistent", **options)


@pytest.mark.parametrize("table, changed_field", [
    ("facility", "callsign"), ("application_facility", "afac_channel"),
    ("app_location", "aloc_lat_ss"),
])
def test_conflicting_primary_keys_fail_explicitly(lms_tables, save_lms, table, changed_field):
    row = dict(lms_tables[table][0])
    row[changed_field] = "21" if changed_field != "callsign" else "OTHER"
    lms_tables[table].append(row)
    with pytest.raises(ValueError, match="conflicting"):
        fcc.load_fcc_lms(save_lms(lms_tables), snapshot_date=SNAPSHOT)


def test_conflicting_antenna_cannot_attach_to_two_sites(lms_tables, save_lms):
    lms_tables["app_location"].append(dict(lms_tables["app_location"][0],
                                          aloc_loc_record_id="second-site"))
    lms_tables["app_antenna"].append(dict(lms_tables["app_antenna"][0],
                                        aant_aloc_loc_record_id="second-site"))
    with pytest.raises(ValueError, match="conflicting antenna"):
        fcc.load_fcc_lms(save_lms(lms_tables), snapshot_date=SNAPSHOT)


def test_identical_records_are_idempotent_and_input_order_is_irrelevant(lms_tables, save_lms):
    for rows in lms_tables.values():
        rows.append(copy.deepcopy(rows[0]))
        rows.reverse()
    rows, stats = fcc.load_fcc_lms(save_lms(lms_tables), snapshot_date=SNAPSHOT)
    assert rows == fcc.load_fcc_lms(FIXTURE, snapshot_date=SNAPSHOT)[0]
    assert stats["duplicate_frequency_rows"] == 1


def test_licensed_reduced_power_and_translator_service(lms_tables, save_lms):
    lms_tables["facility"][0].update(facility_status="LICRP", service_code="LPT")
    rows, _ = fcc.load_fcc_lms(save_lms(lms_tables), snapshot_date=SNAPSHOT)
    assert rows[0]["service_class"] == "Translator"
    assert rows[0]["fcc_status"] == "LICRP"
    assert rows[0]["evidence_status"] == "licensed_candidate"


@pytest.mark.parametrize("change", ["empty", "missing-column", "duplicate-column", "short", "long"])
def test_table_schema_errors_have_context(lms_tables, save_lms, change):
    source = save_lms(lms_tables)
    path = source / "facility.dat"
    lines = path.read_text(encoding="utf-8").splitlines()
    if change == "empty":
        lines = []
    elif change == "missing-column":
        lines[0] = lines[0].replace("facility_id", "renamed_id")
    elif change == "duplicate-column":
        lines[0] = lines[0].replace("facility_id", "callsign")
    elif change == "short":
        lines[1] = "short|row|^|"
    else:
        lines[1] = "extra|" + lines[1]
    path.write_text("\n".join(lines), encoding="utf-8")
    with pytest.raises(ValueError, match="facility.dat"):
        list(fcc.table_rows(source, "facility"))


def test_bom_reordered_columns_whitespace_and_blank_lines(lms_tables, save_lms):
    source = save_lms(lms_tables, trailer=False)
    path = source / "facility.dat"
    lines = path.read_text(encoding="utf-8").splitlines()
    path.write_text("\ufeff" + "\n".join("|".join(reversed(line.split("|")))
                                          for line in lines) + "\n\n", encoding="utf-8")
    assert list(fcc.table_rows(source, "facility"))[0]["callsign"] == "KREM"


@pytest.mark.parametrize("names", [[], ["a/facility.dat", "b/facility.dat"]])
def test_archive_missing_or_ambiguous_member(tmp_path, names):
    path = tmp_path / "bad.zip"
    with ZipFile(path, "w") as archive:
        for name in names:
            archive.writestr(name, "irrelevant")
    with pytest.raises(ValueError, match="exactly one facility.dat"):
        list(fcc.table_rows(path, "facility"))


def test_cli_exports_census_schema_and_reproducible_bytes(tmp_path, run_cli):
    output = tmp_path / "us.csv"
    result = run_cli("ingest/load_fcc_lms.py", FIXTURE, "--snapshot-date", SNAPSHOT,
                     "--output", output)
    assert result.returncode == 0, result.stderr
    with output.open(encoding="utf-8", newline="") as stream:
        row = next(csv.DictReader(stream))
    assert row["schema_version"] == "dtv_transmitter_census_v1"
    assert row["callsign"] == "KREM"
    first = output.read_bytes()
    assert b"\r\n" not in first
    assert fcc.main([str(FIXTURE), "--snapshot-date", SNAPSHOT, "--output", str(output)]) == 0
    assert output.read_bytes() == first


def test_cli_bad_input_preserves_existing_output(tmp_path, capsys):
    output = tmp_path / "keep.csv"
    output.write_text("keep me", encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        fcc.main([str(tmp_path / "missing"), "--snapshot-date", SNAPSHOT,
                  "--output", str(output)])
    assert exc.value.code == 2
    assert "error:" in capsys.readouterr().err
    assert output.read_text(encoding="utf-8") == "keep me"


def test_cli_bad_zip_has_actionable_error(tmp_path, capsys):
    source = tmp_path / "broken.zip"
    source.write_text("not a zip archive", encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        fcc.main([str(source), "--snapshot-date", SNAPSHOT,
                  "--output", str(tmp_path / "output.csv")])
    assert exc.value.code == 2
    assert "not a zip file" in capsys.readouterr().err


@pytest.mark.parametrize("layout", ["dat", "zips", "combined"])
def test_cli_cannot_overwrite_source(lms_tables, save_lms, layout):
    source = save_lms(lms_tables, layout)
    output = source if layout == "combined" else source / (
        "facility.dat" if layout == "dat" else "facility.zip")
    before = output.read_bytes()
    with pytest.raises(SystemExit) as exc:
        fcc.main([str(source), "--snapshot-date", SNAPSHOT, "--output", str(output)])
    assert exc.value.code == 2
    assert output.read_bytes() == before
