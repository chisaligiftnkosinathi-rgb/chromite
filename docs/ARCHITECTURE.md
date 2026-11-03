# Chromite — Target Architecture

Status: accepted direction (Phase 1 audit), extended with owner requirements A–D
(2026-11-03). Chrome only. ZAR. South Africa.

## 1. Decisions
| Decision | Choice |
|---|---|
| Backend | Keep FastAPI + Supabase (Postgres, PostGIS, Auth, Storage) |
| Frontend | Next.js + TypeScript (Supabase Auth for login only; all business logic via the API) |
| Providers | Parent `service_providers` table; existing `laboratories` and `sampling_providers` linked 1:1; new kinds (mineralogy, inspection, courier, other) attach to the parent |
| Personal customers | Single-member organisations (one isolation rule for everyone) |
| Data access | User-scoped Supabase client (RLS enforced) by default; admin client only inside named staff services after a permission check and an audit event |

## 2. Layers
```
Next.js (TypeScript) ──Bearer JWT──► FastAPI
  api/v1/*              thin routers + Pydantic schemas
  core/auth.py          token verification -> AuthenticatedUser
  core/permissions.py   org roles, staff roles, audited superadmin      (Phase 2)
  services/
    catalogue/          materials, tests, methods, packages (versioned)
    requests/           intake: predefined | customised | free text
    recommendation/     requirement A (pure functions)
    review/             requirement D (technical review stage)
    accreditation/      scope matching -> 6 statuses + explanation
    matching/           provider matching with reasons (no auto-award)
    quote_engine/       requirement B — service quotations (pure, Decimal)
    valuation/          requirement B — indicative commodity valuation (separate)
    custody/ results/ reports/ storage/ audit/
  repositories/         database access
Supabase: Postgres + RLS (defence in depth), private Storage + signed URLs,
          append-only platform_audit_logs
```
Pure engines (recommendation, accreditation, matching, quote, valuation) take plain
inputs and return plain outputs with no I/O, so they are deterministic and unit-tested.

## 3. Requirement A — Technical recommendation engine
**Inputs:** material category and physical form; purpose (sale, purchase, export,
beneficiation, process control, verification, environmental); quantity, unit, lot
structure (trucks, bags, stockpiles, consignments); sampling location and presentation
(stockpile, conveyor, truck, bagged, rail, plant feed, tailings); customer requirements
(named tests, accreditation required, turnaround, duplicates or umpire).

**Output — `Recommendation` (stored as an immutable snapshot linked to the request):**
- `sampling_approach`: request type, proposed method, method reference with a recorded
  applicability check (standards are verified for current status before live use;
  nothing is applied blindly outside its stated scope), indicative increments, composites,
  duplicates and retained samples *only where an approved procedure defines them*, and
  required preparation.
- `test_scope[]`: test, analyte and unit, `mandatory | recommended | optional`, a reason for
  each, and the calculation basis for derived results (for example Cr:Fe).
- `reasoning[]`: human-readable rule explanations.
- `assumptions[]`: everything the engine assumed.
- `outstanding_information[]`: what is missing, why it matters, and whether it blocks quoting.
- `confidence`, `requires_technical_review` with its triggers, `ruleset_version`.

Rules live in versioned catalogue tables, not in code. The engine never makes technical
or legal conclusions from results. A competent person can approve, amend or reject any
recommendation (requirement D).

## 4. Requirement B — Two separate commercial modules
| | Service quotation (`quote_engine`) | Indicative commodity valuation (`valuation`) |
|---|---|---|
| Purpose | Price of sampling and testing services | Indicative value of the chrome material |
| Inputs | Evidenced provider price items (source, supplier, dates, unit, VAT treatment, inclusions, expiry, confidence); platform-fee rules; VAT rules | Market benchmarks that are grade-specific (Cr₂O₃ band, product form), dated, sourced, with an explicit delivery basis (Incoterm) and location; dated, sourced exchange rate; evidenced deductions |
| Missing or expired evidence | Line marked *estimate* or *provider quote required*; the quote cannot become firm | No valuation produced; no generic chrome price fallback |
| Output | Versioned quote: line items, quantity, unit price, subtotal, transparent platform fee, VAT, total, validity, assumptions, exclusions, accreditation status | Labelled **indicative only — not an offer or guaranteed price**, showing benchmark, basis, adjustments, assumptions and exclusions |
| Storage | `quotes`, `quote_versions`, `quote_line_items`, `pricing_evidence` | `market_benchmarks`, `exchange_rates`, `material_valuations` |

The modules share no tables, totals or documents. A valuation figure can never appear on a
service quotation. Double charging is prevented through price-item inclusion flags.

## 5. Requirement C — Configurable catalogue with three intake modes
1. **Predefined:** choose packages or services from the catalogue (editable by authorised
   administrators and versioned).
2. **Customised:** add or remove individual tests (optional items only, mandatory items need
   review) and set sampling options.
3. **Free text:** the customer describes the need in plain language. The system proposes a
   structured interpretation, and the customer must confirm it before a final quote.

All three produce the same structured request. Custom materials and tests are stored as
request-level items flagged `custom` and never alter the controlled catalogue.
A plain-language guided mode is the default, with an optional advanced technical mode.

## 6. Requirement D — Human technical review stage
`technical_reviews` with explicit foreign keys to the subject (sampling plan, request test
selection, provider selection), state `pending → approved | changes_requested | rejected`,
reviewer, competence role, decision reason, evidence and timestamps, plus an audit event.

**Mandatory triggers:**
- any sampling plan needing technical judgement (non-standard presentation, method outside
  its scope, unclear lot boundaries);
- tests outside the catalogue, unusual combinations, or Cr(VI) or environmental tests;
- provider selections where the test is non-accredited, out of scope, the scope is
  unverified or expired, or the choice departs from the engine's ranking.

Quote issuance and booking are blocked until the required reviews are approved.
Reviewer roles are configurable (verification officer, operations, or a named competent person).

## 7. Phase map
0 hygiene → 1b consolidated migration (local stack, then approval) → 2 domain and database →
3 catalogue and recommendation (A, C) → 4 request workflow (C, D) →
5 providers and accreditation (D) → 6 quotation and valuation (B) → 7 samples and custody →
8 results and reports → 9 mine intelligence → 10 frontend and end-to-end tests.
