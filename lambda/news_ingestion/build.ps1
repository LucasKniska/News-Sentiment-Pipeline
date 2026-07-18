# Packages lambda/news_ingestion into build/ for deployment: installs Linux/
# cp313 wheels for the compiled deps (lxml via trafilatura, psycopg-binary)
# directly on Windows via uv's cross-platform resolution, then flattens the
# handler source files in alongside them. Does NOT zip - terraform's
# archive_file data source owns that, so source_code_hash tracks changes.
# Re-run this before every `terraform plan`/`apply` that should pick up a
# code or dependency change.
#
# --link-mode copy: this repo lives under OneDrive, which can't hardlink
# between uv's cache and a synced folder - falls back to full copies instead.
#
# Fallback if a future dependency bump lacks a manylinux wheel for cp313
# (this script will fail loudly via --only-binary :all: rather than silently
# producing a wrong-platform binary):
#   docker run --rm `
#     -v "${PWD}:/var/task" -v "${PWD}\build:/build" `
#     public.ecr.aws/sam/build-python3.13:latest `
#     pip install -r /var/task/requirements.txt --target /build

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$buildDir = Join-Path $root "build"

$uv = "$env:USERPROFILE\.local\bin\uv.exe"
if (-not (Test-Path $uv)) {
    $uv = "uv"
}

# Clear the build dir's *contents* rather than removing the directory itself
# and recreating it: this repo lives under OneDrive, whose sync engine can
# hold a lock on the folder object itself (even once empty) for a while
# after a bulk delete, which would make a delete-then-recreate racy here.
if (-not (Test-Path $buildDir)) {
    New-Item -ItemType Directory -Path $buildDir | Out-Null
} else {
    Get-ChildItem -Path $buildDir -Force | Remove-Item -Recurse -Force
}

# boto3/botocore/jmespath/s3transfer are excluded here even though they're in
# requirements.txt (needed for local runs and IDE completeness): every AWS
# Lambda Python runtime already bundles boto3, and botocore's AWS-service
# JSON data alone is ~19MB - re-bundling it would nearly double this
# package's size for a dependency the runtime already provides. If a runtime
# boto3 version mismatch ever causes a problem, drop this filter.
$runtimeProvidedPackages = "boto3", "botocore", "jmespath", "s3transfer"
$filteredRequirementsPath = Join-Path $env:TEMP "news_sentiment_lambda_requirements.txt"
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
    throw "uv pip install failed (exit $LASTEXITCODE) - see the SAM-container fallback in this script's header comment."
}

$sourceFiles = "handler.py", "db.py", "finnhub_client.py", "scraper.py", "transform.py"
foreach ($file in $sourceFiles) {
    Copy-Item (Join-Path $root $file) $buildDir
}

if (Test-Path (Join-Path $buildDir "tzdata")) {
    Write-Warning "build/tzdata is present - the win32-only marker in requirements.txt didn't get excluded for the Linux target. Not fatal (tzdata is harmless extra weight), but worth investigating before relying on --python-platform for future dependency bumps."
}

Write-Host "Build directory ready: $buildDir"
Write-Host "Next: cd terraform; terraform init -upgrade; terraform plan; terraform apply"
