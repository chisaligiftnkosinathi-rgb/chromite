"""Import the chrome pilot seed datasets into a LOCAL Chromite database.

Safety rules (enforced in code):
- Only local databases: host must be localhost, 127.0.0.1, ::1 or a Unix socket.
  Any Supabase-hosted address is refused. There is no override flag.
- Dry run by default: everything runs inside a transaction that is rolled back.
  Pass --apply to commit.
- Records are always imported as unpublished drafts. Mines are marked
  'pending' verification; laboratories 'unverified'. Nothing is published,
  verified or marked accredited, and no accreditation scope rows are created.
- Re-running is safe: mines match on slug, laboratories on name + city. A record
  a reviewer has already touched (published, or verification changed) is never
  overwritten.
- When the audit table exists, one 'seed.import' audit event is written.

Usage (PowerShell, local Supabase stack from tools/db/local-supabase-stack-test.ps1
started with -KeepRunning, or your own local stack):
    $env:PGPASSWORD = "<local stack password>"
    .\\.venv\\Scripts\\python -m app.seeding.importer --dsn "host=127.0.0.1 port=55322 user=postgres dbname=postgres"
    ... add --apply to commit.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

from app.seeding.models import LaboratoryDataset, MineDataset

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MINES = REPO_ROOT / "seed_data" / "chrome" / "mines.pilot.json"
DEFAULT_LABS = REPO_ROOT / "seed_data" / "chrome" / "laboratories.candidates.json"

LOCAL_HOSTS = {"", "localhost", "127.0.0.1", "::1"}
FORBIDDEN_FRAGMENTS = ("supabase.co", "supabase.com", "pooler.")


class UnsafeTargetError(RuntimeError):
    """Raised when the target database is not demonstrably local."""


def assert_local_dsn(dsn: str) -> None:
    from psycopg.conninfo import conninfo_to_dict

    try:
        parts = conninfo_to_dict(dsn)
    except Exception as exc:  # malformed DSN
        raise UnsafeTargetError(f"cannot parse DSN: {type(exc).__name__}") from None

    lowered = " ".join(str(v).lower() for v in parts.values())
    if any(fragment in lowered for fragment in FORBIDDEN_FRAGMENTS):
        raise UnsafeTargetError("refusing a Supabase-hosted address; seeds are local-only")

    for key in ("host", "hostaddr"):
        for host in str(parts.get(key, "")).split(","):
            host = host.strip()
            if host.startswith("/"):
                continue  # Unix socket
            if host not in LOCAL_HOSTS:
                raise UnsafeTargetError(f"refusing non-local {key} {host!r}; seeds are local-only")


def load_datasets(mines_path: Path = DEFAULT_MINES, labs_path: Path = DEFAULT_LABS):
    mines = MineDataset.model_validate(json.loads(mines_path.read_text(encoding="utf-8")))
    labs = LaboratoryDataset.model_validate(json.loads(labs_path.read_text(encoding="utf-8")))
    return mines, labs


@dataclass
class ImportReport:
    applied: bool = False
    mines_inserted: list[str] = field(default_factory=list)
    mines_updated: list[str] = field(default_factory=list)
    mines_preserved: list[str] = field(default_factory=list)
    mines_held_back: list[tuple[str, list[str]]] = field(default_factory=list)
    labs_inserted: list[str] = field(default_factory=list)
    labs_updated: list[str] = field(default_factory=list)
    labs_preserved: list[str] = field(default_factory=list)
    verification_queue: list[str] = field(default_factory=list)
    audit_written: bool = False

    def counts(self) -> dict[str, int]:
        return {
            "mines_inserted": len(self.mines_inserted),
            "mines_updated": len(self.mines_updated),
            "mines_preserved": len(self.mines_preserved),
            "mines_held_back": len(self.mines_held_back),
            "labs_inserted": len(self.labs_inserted),
            "labs_updated": len(self.labs_updated),
            "labs_preserved": len(self.labs_preserved),
            "verification_items": len(self.verification_queue),
        }


_MINE_UPSERT = """
INSERT INTO public.mines (
    slug, mine_name, province, district, nearest_town, latitude, longitude,
    mine_type, operating_status, publication_status, verification_status,
    public_description, source_name, source_url, source_reference, source_checked_at
) VALUES (
    %(slug)s, %(mine_name)s, %(province)s, %(district)s, %(nearest_town)s,
    %(latitude)s, %(longitude)s, %(mine_type)s, %(operating_status)s,
    'draft', 'pending', %(public_description)s, %(source_name)s, %(source_url)s,
    %(source_reference)s, %(source_checked_at)s
)
ON CONFLICT (slug) DO UPDATE SET
    mine_name = EXCLUDED.mine_name,
    province = EXCLUDED.province,
    district = EXCLUDED.district,
    nearest_town = EXCLUDED.nearest_town,
    latitude = EXCLUDED.latitude,
    longitude = EXCLUDED.longitude,
    mine_type = EXCLUDED.mine_type,
    operating_status = EXCLUDED.operating_status,
    public_description = EXCLUDED.public_description,
    source_name = EXCLUDED.source_name,
    source_url = EXCLUDED.source_url,
    source_reference = EXCLUDED.source_reference,
    source_checked_at = EXCLUDED.source_checked_at
WHERE public.mines.publication_status = 'draft'
  AND public.mines.verification_status IN ('unverified', 'pending')
RETURNING (xmax = 0) AS inserted
"""


def _source_reference(source) -> str:
    published = source.published.isoformat() if source.published else "undated"
    return f"{source.kind}; published {published}"


def _import_mines(cur, dataset: MineDataset, report: ImportReport) -> None:
    for mine in dataset.records:
        if mine.missing_required:
            report.mines_held_back.append((mine.slug, mine.missing_required))
            report.verification_queue.append(
                f"mine {mine.slug}: source lacks {', '.join(mine.missing_required)}; find a source"
            )
            continue
        cur.execute(
            _MINE_UPSERT,
            {
                "slug": mine.slug,
                "mine_name": mine.mine_name,
                "province": mine.province,
                "district": mine.district,
                "nearest_town": mine.nearest_town,
                "latitude": mine.latitude,
                "longitude": mine.longitude,
                "mine_type": mine.mine_type,
                "operating_status": mine.operating_status,
                "public_description": mine.public_description,
                "source_name": mine.source.name,
                "source_url": str(mine.source.url),
                "source_reference": _source_reference(mine.source),
                "source_checked_at": mine.source.checked_at,
            },
        )
        row = cur.fetchone()
        if row is None:
            report.mines_preserved.append(mine.slug)
        elif row[0]:
            report.mines_inserted.append(mine.slug)
        else:
            report.mines_updated.append(mine.slug)
        for lead in mine.legal_right_leads:
            report.verification_queue.append(f"mine {mine.slug}: legal-right lead: {lead}")
        report.verification_queue.append(
            f"mine {mine.slug}: confirm identity, status and source before publishing"
        )


def _import_labs(cur, dataset: LaboratoryDataset, report: ImportReport) -> None:
    for lab in dataset.records:
        name = lab.laboratory_name
        values = {
            "laboratory_name": name,
            "city": lab.city,
            "province": lab.province,
            "physical_address": lab.physical_address,
            "website_url": str(lab.website_url) if lab.website_url else None,
            "source_name": lab.source.name,
            "source_url": str(lab.source.url),
            "source_checked_at": lab.source.checked_at,
        }
        cur.execute(
            "SELECT id, publication_status, verification_status FROM public.laboratories"
            " WHERE lower(laboratory_name) = lower(%(laboratory_name)s)"
            " AND lower(coalesce(city, '')) = lower(coalesce(%(city)s, ''))"
            " ORDER BY created_at LIMIT 1",
            values,
        )
        existing = cur.fetchone()
        if existing is None:
            cur.execute(
                "INSERT INTO public.laboratories (laboratory_name, country_code, province, city,"
                " physical_address, website_url, publication_status, verification_status,"
                " source_name, source_url, source_checked_at)"
                " VALUES (%(laboratory_name)s, 'ZA', %(province)s, %(city)s, %(physical_address)s,"
                " %(website_url)s, 'draft', 'unverified', %(source_name)s, %(source_url)s,"
                " %(source_checked_at)s)",
                values,
            )
            report.labs_inserted.append(name)
        elif existing[1] == "draft" and existing[2] == "unverified":
            cur.execute(
                "UPDATE public.laboratories SET province = %(province)s,"
                " physical_address = %(physical_address)s, website_url = %(website_url)s,"
                " source_name = %(source_name)s, source_url = %(source_url)s,"
                " source_checked_at = %(source_checked_at)s WHERE id = %(id)s",
                {**values, "id": existing[0]},
            )
            report.labs_updated.append(name)
        else:
            report.labs_preserved.append(name)
        for claim in lab.accreditation_claims:
            number = claim.accreditation_number_claimed or "no number given"
            report.verification_queue.append(
                f"lab {name}: check SANAS schedule ({number}); claim by {claim.claimed_by}: {claim.claim}"
            )
        if not lab.accreditation_claims:
            report.verification_queue.append(
                f"lab {name}: no accreditation claimed; confirm capability before listing"
            )


def run_import(conn, mines: MineDataset, labs: LaboratoryDataset, apply: bool) -> ImportReport:
    report = ImportReport(applied=apply)
    with conn.transaction(force_rollback=not apply):
        with conn.cursor() as cur:
            _import_mines(cur, mines, report)
            _import_labs(cur, labs, report)
            cur.execute("SELECT to_regclass('public.platform_audit_logs') IS NOT NULL")
            if cur.fetchone()[0]:
                cur.execute(
                    "INSERT INTO public.platform_audit_logs (actor_role, action, resource_type,"
                    " outcome, metadata) VALUES ('seed_importer', 'seed.import', 'seed_dataset',"
                    " 'success', %s::jsonb)",
                    (json.dumps({"datasets": [mines.dataset, labs.dataset], **report.counts()}),),
                )
                report.audit_written = True
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dsn", required=True,
                        help="libpq DSN of a LOCAL database (password via PGPASSWORD)")
    parser.add_argument("--apply", action="store_true", help="commit (default: dry run, rolled back)")
    parser.add_argument("--mines", type=Path, default=DEFAULT_MINES)
    parser.add_argument("--labs", type=Path, default=DEFAULT_LABS)
    args = parser.parse_args(argv)

    try:
        assert_local_dsn(args.dsn)
    except UnsafeTargetError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2

    mines, labs = load_datasets(args.mines, args.labs)

    import psycopg

    with psycopg.connect(args.dsn) as conn:
        report = run_import(conn, mines, labs, apply=args.apply)

    mode = "APPLIED" if report.applied else "DRY RUN (rolled back; add --apply to commit)"
    print(f"Chrome seed import: {mode}")
    for key, value in report.counts().items():
        print(f"  {key}: {value}")
    for slug, missing in report.mines_held_back:
        print(f"  held back: {slug} (missing {', '.join(missing)})")
    print(f"  audit event: {'written' if report.audit_written and report.applied else 'would be written' if report.audit_written else 'skipped (no audit table)'}")
    print("\nVerification queue:")
    for item in report.verification_queue:
        print(f"  - {item}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
