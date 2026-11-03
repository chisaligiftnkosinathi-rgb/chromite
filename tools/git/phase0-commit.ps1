<#
.SYNOPSIS
  Creates the local Chromite Git repository with two verified commits:
    1. "Baseline" — the code exactly as found before Phase 0 (from .phase0-baseline\)
    2. "Phase 0"  — repository hygiene changes
.DESCRIPTION
  Local only: no remote is added, nothing is pushed.
  Aborts if .env, ZIPs, backups, supabase\.temp, local data or secret-looking
  content would be committed, or if the staged files differ from the expected list.
  Run from anywhere:  powershell -ExecutionPolicy Bypass -File tools\git\phase0-commit.ps1
#>
[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
Set-Location $Root

$script:Initialised = $false
function Fail($m) {
    Write-Host "ABORTED: $m" -ForegroundColor Red
    if ($script:Initialised) {
        Write-Host 'Nothing was pushed. To start again after fixing the cause, delete only the new'
        Write-Host 'repository metadata and re-run:  Remove-Item -Recurse -Force .git'
    }
    exit 1
}
function Step($m) { Write-Host "`n== $m" -ForegroundColor Cyan }
$GitExe = (Get-Command git -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1).Source
# Named Invoke-Git: PowerShell names are case-insensitive, so a function called 'Git' would shadow git.exe.
function Invoke-Git { & $GitExe @args; if ($LASTEXITCODE -ne 0) { Fail "git $($args -join ' ') failed" } }

$BaselineFiles = @(
    '.env.example', '.gitattributes', '.gitignore', 'README.md',
    'app/__init__.py', 'app/api/__init__.py', 'app/api/v1/__init__.py',
    'app/api/v1/batches.py', 'app/api/v1/mines.py', 'app/core/__init__.py',
    'app/core/config.py', 'app/core/supabase.py', 'app/main.py',
    'app/models/__init__.py', 'app/schemas/__init__.py', 'app/schemas/batch.py',
    'app/schemas/mine.py', 'app/services/__init__.py',
    'package-lock.json', 'package.json', 'requirements.txt',
    'supabase/migrations/20261103142214_initial_chromite_schema.sql',
    'supabase/migrations/20261103170000_chromite_least_privilege_permissions.sql',
    'tests/__init__.py'
)
$Phase0NewFiles = @(
    '.githooks/pre-commit', 'pytest.ini', 'requirements-dev.txt',
    'app/core/auth.py', 'app/core/logging.py',
    'docs/ARCHITECTURE.md', 'docs/IMPLEMENTATION_LOG.md', 'docs/SECURITY_NOTES.md',
    'supabase/migrations-proposed/README.md',
    'supabase/migrations-proposed/20261104090000_consolidated_grants_rls_superadmin_audit.sql',
    'supabase/migrations-proposed/20261104090000_consolidated_grants_rls_superadmin_audit.ROLLBACK.sql',
    'tests/conftest.py', 'tests/test_auth.py', 'tests/test_config.py', 'tests/test_cors.py',
    'tests/test_env_isolation.py', 'tests/test_logging.py', 'tests/test_mines.py',
    'tests/test_repo_hygiene.py', 'tests/test_routes.py',
    'tests/db/README.md', 'tests/db/test_migration_replay.py',
    'tests/db/sql/stand_in_cluster.sql', 'tests/db/sql/stand_in_database.sql',
    'tools/db/local-supabase-stack-test.ps1', 'tools/db/local_stack_probe.sql',
    'tools/git/phase0-commit.ps1'
)
$Phase0ChangedFiles = @('.env.example', 'README.md', 'app/api/v1/mines.py',
                        'app/core/config.py', 'app/main.py', 'requirements.txt')
$AllFiles = ($BaselineFiles + $Phase0NewFiles) | Sort-Object -Unique

$MustBeIgnored = @('.env', '.env.local', 'chromite-backend-review.zip', 'app/core/config.py.backup',
    'app/core/supabase.py.backup', 'chromite_structure.txt', 'supabase/.temp/project-ref',
    'supabase/.branches/_current_branch', 'data/x', 'records/x', '_archive/x',
    '.phase0-baseline/x', '.venv/x', 'node_modules/x')

$BlockedPath = '(^|/)\.env($|\.)|\.zip$|\.backup$|(^|/)supabase/\.(temp|branches)/|^data/|^records/|^_archive/|^\.phase0-baseline/|^node_modules/|^\.venv/|chromite_structure\.txt$'
$SecretRegex = 'sb_(secret|publishable)_[A-Za-z0-9_-]{16,}|eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}|postgres(ql)?://[^:/@\s]+:[^@\s]{3,}@'

function Assert-StagedSafe([string[]]$Expected) {
    $staged = @(& $GitExe diff --cached --name-only --diff-filter=ACMR) | Sort-Object
    $bad = $staged | Where-Object { $_ -match $BlockedPath -and $_ -notmatch '(^|/)\.env\.example$' }
    if ($bad) { Fail "blocked paths staged: $($bad -join ', ')" }
    $added = (& $GitExe diff --cached --diff-filter=ACMR -U0) | Where-Object { $_ -like '+*' }
    $hits = $added | Select-String -Pattern $SecretRegex
    if ($hits) { Fail "secret-looking content staged ($($hits.Count) line(s)); inspect with: git diff --cached" }
    $diff = Compare-Object ($Expected | Sort-Object) $staged
    if ($diff) { $diff | Format-Table | Out-String | Write-Host; Fail 'staged files differ from the expected list' }
    Write-Host "Verified $($staged.Count) staged file(s): no blocked paths, no secret patterns, list matches." -ForegroundColor Green
}

# --- Preconditions -------------------------------------------------------------
Step 'Preconditions'
if (-not $GitExe) { Fail 'git is not installed' }
if (Test-Path '.git') { Fail '.git already exists — this script only creates a new repository' }
if (-not (Test-Path '.phase0-baseline')) { Fail '.phase0-baseline\ is missing' }
foreach ($f in $AllFiles) { if (-not (Test-Path $f)) { Fail "missing expected file: $f" } }
foreach ($f in $BaselineFiles) { if (-not (Test-Path (Join-Path '.phase0-baseline' $f))) { Fail "missing baseline copy: $f" } }
$name = (& $GitExe config --get user.name); $email = (& $GitExe config --get user.email)
if (-not $name -or -not $email) {
    Fail 'Set your identity first: git config --global user.name "Your Name"; git config --global user.email "you@example.com"'
}
Write-Host "Author: $name <$email>"

Step 'git init (local only)'
Invoke-Git init -b main
$script:Initialised = $true
Invoke-Git config core.fileMode false
Invoke-Git config core.hooksPath .githooks

Step 'Verify .gitignore before staging anything'
foreach ($p in $MustBeIgnored) {
    & $GitExe check-ignore -q --no-index -- $p
    if ($LASTEXITCODE -ne 0) { Fail "not ignored: $p" }
}
& $GitExe check-ignore -q --no-index -- '.env.example'
if ($LASTEXITCODE -eq 0) { Fail '.env.example is ignored but must be tracked' }
Write-Host "All $($MustBeIgnored.Count) private paths ignored; .env.example trackable." -ForegroundColor Green

Step 'Commit 1: baseline (code as found)'
Invoke-Git --work-tree=.phase0-baseline add -A -- .
Assert-StagedSafe $BaselineFiles
Invoke-Git commit -q -m "Baseline: Chromite backend as found before Phase 0" -m "Original files only. No secrets, local data, backups or archives."

Step 'Commit 2: Phase 0'
Invoke-Git add -- $AllFiles
Invoke-Git add --chmod=+x -- .githooks/pre-commit   # executable for Linux/macOS clones
$tracked = @(& $GitExe ls-files) | Sort-Object
$cmp = Compare-Object ($AllFiles | Sort-Object) $tracked
if ($cmp) { $cmp | Format-Table | Out-String | Write-Host; Fail 'tracked files differ from the expected list' }
$changed = @(& $GitExe diff --cached --name-only --diff-filter=M) | Sort-Object
$cmpChanged = Compare-Object ($Phase0ChangedFiles | Sort-Object) $changed
if ($cmpChanged) { $cmpChanged | Format-Table | Out-String | Write-Host; Fail 'modified-file set differs from the expected list' }
Assert-StagedSafe (($Phase0NewFiles + $Phase0ChangedFiles) | Sort-Object -Unique)
$untracked = @(& $GitExe ls-files --others --exclude-standard)
$unstaged = @(& $GitExe diff --name-only)
if ($untracked -or $unstaged) {
    ($untracked + $unstaged) | Write-Host
    Fail 'untracked (not ignored) or unstaged files remain'
}
Invoke-Git commit -q -m "Phase 0: repository hygiene, CORS/config fixes, auth dependency, tests" -m "See docs/IMPLEMENTATION_LOG.md. Proposed migration kept outside supabase/migrations/. Hosted Supabase unchanged."

Step 'Result'
Invoke-Git log --oneline
Write-Host "Tracked files: $((& $GitExe ls-files).Count)"
Invoke-Git status --short --branch
Write-Host "`nDone. No remote configured; nothing pushed." -ForegroundColor Green
Write-Host 'You may now delete the .phase0-baseline folder (it is git-ignored).'
