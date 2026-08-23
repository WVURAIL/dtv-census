#!/usr/bin/env python3
"""Filter an ISED SMS data extract to a frequency window.

The Canada-SMS-Allocations snapshot (team SharePoint,
``RFI Mitigation/Canada-SMS-Allocations/``) holds five ISED open-data
extracts. The two large ones (``tsl_data.csv``, 979 MB; ``as_data.csv``,
476 MB) exceed what this repository should carry, so committed subsets are
produced by this filter instead of vendoring the full files.

Each ``X_data.csv`` is documented by its ``X_field_desc.pdf``, committed
under ``sources/ised/field_descriptions/``. ``tsl_data.csv`` and
``ssl_data.csv`` carry a header row with a ``tx_frequency`` column in MHz;
files without a header row (``ws_data.csv``, ``as_data.csv``,
``afl_data.csv``) need ``--field-index`` (0-based) instead, with the column
read off the field-description PDF.

    python3 extract_tv_records.py raw/tsl_data.csv raw/tv_band_tsl.csv
    python3 extract_tv_records.py --lo 400 --hi 800 raw/tsl_data.csv raw/chime_band_tsl.csv

The default window is the post-repack ATSC UHF band, 470-608 MHz
(physical channels 14-36); CHIME's full band is 400-800 MHz.
"""
from __future__ import annotations

import argparse
import csv
import sys


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("src", help="input CSV (an ISED *_data.csv extract)")
    ap.add_argument("dst", help="output CSV, filtered rows only")
    ap.add_argument("--field", default="tx_frequency",
                    help="header name of the frequency column in MHz "
                         "(default: tx_frequency)")
    ap.add_argument("--field-index", type=int, default=None,
                    help="0-based frequency column index, for extracts "
                         "without a header row")
    ap.add_argument("--lo", type=float, default=470.0,
                    help="window lower edge in MHz (default 470)")
    ap.add_argument("--hi", type=float, default=608.0,
                    help="window upper edge in MHz (default 608)")
    args = ap.parse_args(argv)

    n_in = n_out = n_blank = 0
    with open(args.src, newline="", encoding="utf-8", errors="replace") as fin, \
         open(args.dst, "w", newline="", encoding="utf-8") as fout:
        reader = csv.reader(fin)
        writer = csv.writer(fout)
        if args.field_index is None:
            header = next(reader)
            try:
                idx = header.index(args.field)
            except ValueError:
                names = ", ".join(header[:12])
                sys.exit(f"no column {args.field!r} in header ({names}, ...); "
                         f"use --field or --field-index")
            writer.writerow(header)
        else:
            idx = args.field_index
        for row in reader:
            n_in += 1
            try:
                mhz = float(row[idx])
            except (IndexError, ValueError):
                n_blank += 1
                continue
            if args.lo <= mhz < args.hi:
                writer.writerow(row)
                n_out += 1

    print(f"{args.src}: {n_in:,} rows in, {n_out:,} in "
          f"[{args.lo:g}, {args.hi:g}) MHz -> {args.dst} "
          f"({n_blank:,} rows had no parseable frequency)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
