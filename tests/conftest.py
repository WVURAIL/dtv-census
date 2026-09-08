"""Small source-format fixtures; no network or bulk SharePoint data required."""
from __future__ import annotations

import csv
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "census"), str(REPO / "ingest")]


@pytest.fixture
def workbook_row():
    def make(**changes):
        row = {
            "Type": "on-air", "Physical Ch(s)": 14, "Call Sign": "TEST-DT",
            "Class": "Relay", "Field Strength (dBuV/m)": 12.345,
            "Distance to DRAO (mi)": 10.0,
            "Bearing from DRAO (deg, True)": 90.0,
            "Frequency Tolerance": "±1 kHz", "CHIME Ch Index": 844,
            "Nominal Pilot Freq (MHz)": 470.309441,
            "City": "Test Town", "State/Prov": "BC",
            "Latitude": 49.0, "Longitude": -119.0,
        }
        row.update(changes)
        return row
    return make


@pytest.fixture
def workbook_file(tmp_path, workbook_row):
    def write(rows):
        path = tmp_path / "stations.xlsx"
        pd.DataFrame(rows, columns=workbook_row().keys()).to_excel(path, index=False)
        return path
    return write


@pytest.fixture
def ised_record():
    # Literal positions exercise the documented 19-column upstream format,
    # independently of the parser's column constants.
    def make(callsign="TEST-DT", frequency="473", flag="D", kind="1",
             lat="49:0:0", lon="119:0:0", erp="30", name="Test Town", prov="BC"):
        return [kind, "T", "licence", "Owner", name, callsign, "1", "BT",
                lat, lon, "100", "", prov, erp, "20", flag, "6M00C7W",
                "6000", frequency]
    return make


@pytest.fixture
def csv_file(tmp_path):
    def write(rows, name="source.csv"):
        path = tmp_path / name
        with path.open("w", encoding="utf-8", newline="") as stream:
            csv.writer(stream).writerows(rows)
        return path
    return write


@pytest.fixture
def run_cli(tmp_path):
    def run(script, *args):
        # A different cwd catches accidental reliance on the caller's directory.
        return subprocess.run(
            [sys.executable, str(REPO / script), *map(str, args)],
            cwd=tmp_path, capture_output=True, text=True, encoding="utf-8",
            timeout=60, check=False,
        )
    return run
