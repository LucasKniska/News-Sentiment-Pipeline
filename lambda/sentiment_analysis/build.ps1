# Packages lambda/sentiment_analysis into build/ for deployment - same
# approach as lambda/news_ingestion/build.ps1 (see its header comment for the
# full rationale): Linux/cp313 wheels via uv's cross-platform resolution
# (needed here for psycopg-binary and pydantic-core, both compiled), source
# files flattened in alongside them, no zipping (terraform's archive_file
# data source owns that). Re-run before every `terraform plan`/`apply` that
# should pick up a code or dependency change.
#
# requirements.txt here is exported from pyproject.toml's `langchain`
# dependency group only (`uv export --only-group langchain`), not the root
# dependency list - it deliberately excludes news_ingestion-only deps
# (trafilatura/finnhub-python) that this component never imports.

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$buildDir = Join-Path $root "build"

$uv = "$env:USERPROFILE\.local\bin\uv.exe"
if (-not (Test-Path $uv)) {
    $uv = "uv"
}

# Clear the build dir's *contents* rather than removing the directory itself -
# see build.ps1's counterpart in news_ingestion for why (OneDrive sync lock).
if (-not (Test-Path $buildDir)) {
    New-Item -ItemType Directory -Path $buildDir | Out-Null
} else {
    Get-ChildItem -Path $buildDir -Force | Remove-Item -Recurse -Force
}

# boto3/botocore/jmespath/s3transfer are excluded here even though they're in
# requirements.txt (needed for local runs and IDE completeness): every AWS
# Lambda Python runtime already bundles boto3 - see news_ingestion/build.ps1
# for the full size-cost rationale.
$runtimeProvidedPackages = "boto3", "botocore", "jmespath", "s3transfer"
$filteredRequirementsPath = Join-Path $env:TEMP "sentiment_analysis_lambda_requirements.txt"
Get-Content (Join-Path $root "requirements.txt") | Where-Object {
    if ($_ -match '^([A-Za-z0-9_.-]+)\s*==') {
        $runtimeProvidedPackages -notcontains $matches[1].ToLower()
    } else {
        $true
    }
} | Set-Content -Path $filteredRequirementsPath -Encoding utf8

& $uv pip install `
    --target $buildDir `
    --python-platform x86_64-manylinux2014 `
    --python-version 3.13 `
    --only-binary :all: `
    --link-mode copy `
    -r $filteredRequirementsPath
if ($LASTEXITCODE -ne 0) {
    throw "uv pip install failed (exit $LASTEXITCODE) - see the SAM-container fallback in news_ingestion/build.ps1's header comment; the same fallback applies here."
}

$sourceFiles = "handler.py", "run.py", "chain.py", "combine_chain.py", "db.py", "models.py", "schema.py", "aggregate.py"
foreach ($file in $sourceFiles) {
    Copy-Item (Join-Path $root $file) $buildDir
}

if (Test-Path (Join-Path $buildDir "tzdata")) {
    Write-Warning "build/tzdata is present - the win32-only marker in requirements.txt didn't get excluded for the Linux target. Not fatal, but worth investigating before relying on --python-platform for future dependency bumps."
}

Write-Host "Build directory ready: $buildDir"
Write-Host "Next: cd terraform; terraform init -upgrade; terraform plan; terraform apply"
