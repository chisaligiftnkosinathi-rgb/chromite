# Chrome seed data (pilot)

Candidate records for the mine and laboratory directories. **Nothing here is verified.**
The importer loads every record as an unpublished draft; a verification officer must review
each one before it can be published.

| File | Records | Imported as |
| --- | --- | --- |
| `mines.pilot.json` | 9 mines (5 importable, 4 held back: source gives no province) | `draft` / `pending` |
| `laboratories.candidates.json` | 8 laboratories; 5 accreditation claims (3 say accredited, 2 say accreditation is being pursued) | `draft` / `unverified`, no accreditation scope rows |

## Rules for adding records
- Every record cites a source opened by a person: name, https URL, date checked, kind
  (`official_government`, `company_primary`, `company_press_release`, `conference_paper`, `trade_press`).
- Only facts the source states. Unknown stays `null`. No coordinates unless the source gives them.
- A mine listing is not proof of a mining right, current operation or production. Legal-right
  information goes in `legal_right_leads` until verified against official records.
- A laboratory is never marked accredited from a seed. Claims go in `accreditation_claims` with
  `status: "unverified"` and a `claim_type` (`states_accredited` or `pursuing_accreditation`); accreditation is verified per test against the current SANAS schedule
  (facility number, certificate validity, scope revision, analyte, method, material, site).
- Government directories: confirm the reuse terms before copying their data into a commercial product.
  These pilot files use company and published sources only.

## Not yet sourced
- Samancor Chrome laboratory (lead from owner's notes: SANAS T0123). No source examined yet, so no record.

## Run (local database only)
```powershell
$env:PGPASSWORD = "<local password>"
.\.venv\Scripts\python -m app.seeding.importer --dsn "host=127.0.0.1 port=55322 user=postgres dbname=postgres"          # dry run
.\.venv\Scripts\python -m app.seeding.importer --dsn "host=127.0.0.1 port=55322 user=postgres dbname=postgres" --apply  # commit
```
The importer refuses any non-local or Supabase-hosted address, `service=` connections and a set
`PGHOSTADDR`/`PGSERVICE`, and re-checks the connected address. It is insert-only: a record that
already exists is never modified, so reviewer edits always survive a re-run.

## Sources used (checked 3 November 2026)
- [Tharisa plc: Tharisa Minerals](https://tharisa.com/tharisa-minerals.php)
- [Assmang: Dwarsrivier Chrome Mine stake sale (25 June 2015)](https://assmang.co.za/?p=3441)
- [M. Visser, Samancor Chrome overview, Southern African Pyrometallurgy 2006, SAIMM](https://redesign.911metallurgist.com/wp-content/uploads/2024/03/An-Overview-of-the-History-and-Current-Operational-Facilities-of-Samancor-Chrome.pdf)
- [Mining Weekly: Glencore mineral status (30 January 2026)](https://www.miningweekly.com/article/glencore-spells-out-mineral-status-across-africa-australia-americas-2026-01-30)
- [Cotecna: South Africa gains ISO 17025 accreditation (12 April 2022)](https://www.cotecna.com/en/media/news/cotecna-south-africa-gains-iso17025-accreditation)
- [AHK capability statement, South Africa (19 February 2025)](https://www.ahkgroup.com/wp-content/uploads/2025/02/AHK_CapabilityStatement_SouthAfrica-190225-1.pdf)
- [Mitra SK: Global network, Africa](https://mitrask.com/global-network-africa)
- [IMEC Laboratory Services](https://imeclab.co.za/)
