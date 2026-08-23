# raw/ — local working copies (not committed)

This directory is gitignored. Use it for local copies of the large raw
extracts when running `ingest/extract_tv_records.py`.

Get the snapshots from the team SharePoint:

    WVU RAIL - Documents/RFI Mitigation/Canada-SMS-Allocations/
    WVU RAIL - Documents/RFI Mitigation/Station-Lists/

or refresh them from the upstream publishers (the ISED extracts are updated
daily or monthly from the licensing database, so a fresh download is a *new*
snapshot — record the retrieval date if you replace the SharePoint copy):

- ISED Spectrum Management System data extracts (tsl/as/ssl/afl/ws):
  https://open.canada.ca/ (search "Spectrum Management System data")
- RabbitEars station database and Signal Search Map: https://rabbitears.info/
- FCC Licensing and Management System (LMS): https://enterpriseefiling.fcc.gov/
