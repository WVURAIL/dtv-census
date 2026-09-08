from __future__ import annotations

import csv

import pytest

from extract_tv_records import main


def read_rows(path):
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.reader(stream))


def test_header_filter_boundaries_malformed_rows_and_counters(csv_file, tmp_path,
                                                            capsys):
    header = ["name", "tx_frequency", "note"]
    inside = [["lower", "470", 'quoted, "value"'],
              ["upper", "607.999999", "Québec"]]
    source = csv_file([header, *inside, ["low", "469.999"], ["high", "608"],
                       ["blank", ""], ["text", "bad"], ["short"], []])
    destination = tmp_path / "out.csv"
    assert main([str(source), str(destination)]) == 0
    assert read_rows(destination) == [header, *inside]
    assert "8 rows in, 2 in [470, 608) MHz" in capsys.readouterr().out


@pytest.mark.parametrize("options, rows, expected", [
    (["--field", "mhz", "--lo", "400", "--hi", "800"],
     [["mhz", "name"], ["400", "first"], ["799.99", "last"], ["800", "out"]],
     [["mhz", "name"], ["400", "first"], ["799.99", "last"]]),
    (["--field-index", "0"], [["470", "first"], ["608", "out"]],
     [["470", "first"]]),
    (["--field-index", "1"], [["first", "4.73e2"], ["out", "900"]],
     [["first", "4.73e2"]]),
    ([], [["tx_frequency"]], [["tx_frequency"]]),
    (["--field-index", "0"], [], []),
])
def test_input_layouts_and_custom_window(csv_file, tmp_path, options, rows, expected):
    source = csv_file(rows)
    destination = tmp_path / "out.csv"
    assert main([str(source), str(destination), *options]) == 0
    assert read_rows(destination) == expected


def test_bad_encoding_is_replaced_and_nonfinite_frequencies_are_counted(
    tmp_path, capsys,
):
    source = tmp_path / "in.csv"
    source.write_bytes(b"name,tx_frequency\nbad\xff,473\na,nan\nb,inf\nc,-inf\n")
    destination = tmp_path / "out.csv"
    assert main([str(source), str(destination)]) == 0
    assert read_rows(destination) == [["name", "tx_frequency"], ["bad\ufffd", "473"]]
    assert "3 rows had no parseable frequency" in capsys.readouterr().out


@pytest.mark.parametrize("rows, message", [
    ([], "empty"), ([["station", "frequency"]], "no column"),
])
def test_invalid_header_preserves_existing_destination(csv_file, tmp_path,
                                                      rows, message, capsys):
    source = csv_file(rows)
    destination = tmp_path / "out.csv"
    destination.write_text("keep existing output", encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        main([str(source), str(destination)])
    assert exc.value.code == 2
    assert message in capsys.readouterr().err.lower()
    assert destination.read_text(encoding="utf-8") == "keep existing output"


@pytest.mark.parametrize("options", [
    ["--lo", "608", "--hi", "470"], ["--lo", "470", "--hi", "470"],
    ["--lo", "nan"], ["--hi", "inf"], ["--field-index", "-1"],
])
def test_invalid_options_fail_before_creating_output(csv_file, tmp_path, options):
    source = csv_file([["tx_frequency"], ["473"]])
    destination = tmp_path / "out.csv"
    with pytest.raises(SystemExit) as exc:
        main([str(source), str(destination), *options])
    assert exc.value.code == 2
    assert not destination.exists()


@pytest.mark.parametrize("alias", ["same", "symlink", "hardlink"])
def test_source_cannot_be_overwritten(csv_file, tmp_path, alias):
    source = csv_file([["tx_frequency"], ["473"]])
    before = source.read_bytes()
    destination = source
    if alias != "same":
        destination = tmp_path / "alias.csv"
        try:
            if alias == "symlink":
                destination.symlink_to(source)
            else:
                destination.hardlink_to(source)
        except OSError as exc:
            pytest.skip(f"Filesystem does not support {alias}: {exc}")
    with pytest.raises(SystemExit) as exc:
        main([str(source), str(destination)])
    assert exc.value.code == 2
    assert source.read_bytes() == before


def test_filter_cli_entrypoint(csv_file, tmp_path, run_cli):
    source = csv_file([["tx_frequency"], ["473"]])
    destination = tmp_path / "out.csv"
    result = run_cli("ingest/extract_tv_records.py", source, destination)
    assert result.returncode == 0, result.stderr
    assert read_rows(destination) == [["tx_frequency"], ["473"]]


def test_large_input_is_streamed(tmp_path, capsys):
    # A single-pass source that rejects bulk reads makes streaming an explicit
    # contract without a flaky wall-clock or memory threshold.
    import builtins
    from unittest.mock import patch

    class StreamingInput:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def __iter__(self):
            yield "tx_frequency\n"
            for _ in range(20_000):
                yield "473\n"

        def read(self, *args):
            raise AssertionError("input must be streamed")

        readlines = read

    original_open = builtins.open
    source = tmp_path / "large.csv"
    source.touch()
    destination = tmp_path / "out.csv"

    def open_stream(path, *args, **kwargs):
        if str(path) == str(source):
            return StreamingInput()
        return original_open(path, *args, **kwargs)

    with patch("builtins.open", side_effect=open_stream):
        assert main([str(source), str(destination)]) == 0
    assert len(read_rows(destination)) == 20_001
    assert "20,000 rows in, 20,000 in" in capsys.readouterr().out
