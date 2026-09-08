# USA / FCC LMS loading

`ingest/load_fcc_lms.py` loads US broadcast-TV records directly from FCC LMS
public database tables. It accepts extracted `.dat` tables, a directory of
individual table ZIPs, or a combined LMS ZIP. Loading is offline and streams
each table; only relevant joins and output records are retained in memory.

Obtain a single dated snapshot from the FCC's
[LMS Public Database Files](https://enterpriseefiling.fcc.gov/dataentry/public/tv/lmsDatabase.html).
Keep large downloads under the ignored `raw/` directory. Download these six
tables from the same snapshot, or use the combined archive:

- `facility`
- `license_filing_version`
- `application_facility`
- `app_location`
- `app_antenna`
- `app_antenna_frequency`

The [FCC LMS schema](https://enterpriseefiling.fcc.gov/dataentry/api/download/lmschema)
describes the columns. The table headers govern actual column order. Files
are unquoted, pipe-delimited records with a `|^|` trailer. The loader also
accepts tables without that trailer, UTF-8 BOMs, and reordered columns;
missing/duplicate headers, corrupt row widths and conflicting join records
produce errors with context.

## Run

From the repository root after installing `requirements.txt`:

```bash
python ingest/load_fcc_lms.py raw/fcc-lms-2026-09-08 \
  --snapshot-date 2026-09-08 --output raw/fcc_uhf.csv

# A combined download and a different center/radius:
python ingest/load_fcc_lms.py raw/Current_LMS_Dump.zip \
  --snapshot-date 2026-09-08 --center 47.6 -122.3 --radius-mi 120 \
  --output raw/fcc_seattle.csv
```

Supply the download's actual snapshot date; the loader does not infer it
from the clock or archive name. Default center is DRAO, radius 500 statute
miles, and physical channel range 14–36. The radius includes its boundary.
The Python API is `load_fcc_lms(source, snapshot_date="YYYY-MM-DD", ...)`,
returning `(rows, diagnostic_counts)`.

## Selection and joins

1. Select active digital television facilities with status `LICEN` or
   `LICRP`. The service mapping includes full power, Class A, low power,
   translators/replacement translators and their DTS equivalents. Analog,
   radio, auxiliary-only services, silent/suspended/cancelled facilities and
   facility records flagged ATSC 3.0 are excluded.
2. Follow `facility.latest_filing_version_id` to exactly that
   `license_filing_version.filing_version_id`. Require an active, granted
   (`GRA`) licence (`L`) with the same licence ID and a digital TV service.
   A newer construction-permit application does not replace the licence.
   An unresolved current pointer produces no output for that facility.
3. Join `application_facility.afac_application_id` to the filing ID and
   confirm the facility ID, country `US`, active flag and ATSC 3.0 flag.
4. Join `app_location.aloc_aapp_application_id` to the filing. Exclude
   inactive records and DTS reference locations. Parse the NAD83 DMS fields,
   applying hemisphere signs; invalid coordinates are counted and skipped.
   Compute the great-circle distance using the same spherical model as ISED.
5. Join active antennas through their location IDs and active frequency
   records through antenna IDs. Use the physical antenna channel, falling
   back to the application's physical channel when blank. Virtual channel
   numbers are never used.

Deduplicate by facility ID, site ID and physical channel, retaining the
highest known ERP. Separate DTS sites remain separate records. Separate
licensees sharing a channel remain separate until their physical-carrier
sharing relationship is adjudicated.

FCC ERP is already in **kW**. Use total ERP when present, then maximum ERP,
then the maximum specified horizontal/vertical ERP. Polarization powers
are not summed. Missing, negative or non-finite power becomes blank and
invalid power is counted. `LICRP` retains the published licensed value;
that value is not a measurement of current reduced-power operation.

## Output and limits

The CSV carries the census v1 columns plus ERP, latitude/longitude, datum,
facility/application/site/licence IDs, FCC service/status, source and snapshot
date. Every row is `licensed_candidate`. `detectability_db` stays blank;
licensing alone does not establish an emission, ATSC pilot detection or
historical on/off dates. ATSC 3.0 exclusion depends on the published flags.
Coordinates are labelled **NAD83**, with no silent conversion to WGS84.

This is a USA loading stage. It does not automatically replace the historical
US workbook rows in `census/census.csv`, adjudicate channel sharing, or claim
that today's records verify the older workbook snapshot. The existing census
continues to regenerate byte for byte. Inspect `facilities_without_output`
and the intermediate join/filter counts when auditing snapshot completeness;
that count includes facilities outside the requested radius or UHF range.

An initial full-snapshot run on 2026-09-08 read 181,038 facility records and
produced 515 candidate site/channel rows within 500 miles of DRAO. This is
a dated smoke check, not a count that future FCC releases must reproduce.
The small KREM fixture under `tests/fixtures/fcc_lms/` contains source rows
and download hashes for a repeatable offline regression.
