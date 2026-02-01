<#
cleanup.ps1 - Deep Windows cleanup with Dry-Run, LogLevel, and JSON Preview support.

Usage:
  cleanup.ps1 [--dry-run] [--loglevel info|warn|error|all] [--json]
- --dry-run: don't delete, only list
- --loglevel: minimum level to emit (info|warn|error|all)
- --json: when combined with --dry-run, output structured JSON to stdout describing items that would be deleted

JSON format:
  { "items": [ {"path": "C:\\...","type":"file|dir"}, ... ] }

The script emits textual logs prefixed like "INFO: message" (so the GUI can filter by level).
#>

Param(
    [switch] $dryrun,
    [string] $loglevel = "info",
    [switch] $json
)

$levels = @{ "info"=1; "warn"=2; "error"=3; "all"=0 }
function ShouldLog([string]$lvl) { return $levels[$lvl] -ge $levels[$loglevel] -or $loglevel -eq "all" }

function Log($level, $message) {
    if (ShouldLog($level)) { Write-Output ("{0}: {1}" -f $level.ToUpper(), $message) }
}

$ErrorActionPreference = "SilentlyContinue"
Log "info" ("Script started. dryrun={0} loglevel={1} json={2}" -f $dryrun, $loglevel, $json)

# helper collect list for preview
$previewItems = @()

function AddPreview($path, $type) {
    $previewItems += @{ path = $path; type = $type }
}

function SafeRemove($path) {
    if (-not (Test-Path $path)) { Log "info" ("Not found: {0}" -f $path); return }
    Log "info" ("Clearing: {0}" -f $path)
    AddPreview $path "dir"
    if (-not $dryrun) {
        Try {
            Get-ChildItem -Path $path -Recurse -Force | Remove-Item -Force -Recurse -ErrorAction SilentlyContinue
            Log "info" ("Cleared: {0}" -f $path)
        } Catch { Log "warn" ("Failed clearing {0}: {1}" -f $path, $_) }
    } else {
        Log "info" ("(DRY-RUN) Would clear: {0}" -f $path)
    }
}

# Windows Update (SoftwareDistribution\Download)
$download = "$env:windir\SoftwareDistribution\Download"
if (Test-Path $download) { AddPreview $download "dir" }
SafeRemove $download

# catroot2
$catroot2 = "$env:windir\System32\catroot2"
if (Test-Path $catroot2) { AddPreview $catroot2 "dir" }
SafeRemove $catroot2

# Temp locations (expanded globs)
$paths = @("$env:TEMP", "$env:windir\Temp", "$env:LOCALAPPDATA\Temp")
foreach ($p in $paths) {
    if (Test-Path $p) {
        AddPreview $p "dir"
        if ($dryrun) { Log "info" ("(DRY-RUN) Would clear contents of {0}" -f $p) }
        else {
            Try {
                Get-ChildItem -Path $p -Recurse -Force | Remove-Item -Force -Recurse -ErrorAction SilentlyContinue
                Log "info" ("Cleared: {0}" -f $p)
            } Catch { Log "warn" ("Failed clearing {0}: {1}" -f $p, $_) }
        }
    } else {
        Log "info" ("Not found: {0}" -f $p)
    }
}

# Prefetch
$prefetch = "$env:SystemRoot\Prefetch"
if (Test-Path $prefetch) { AddPreview $prefetch "dir" }
if ($dryrun) { Log "info" "(DRY-RUN) Would clear Prefetch" } else {
    Try { Get-ChildItem -Path $prefetch -Force | Remove-Item -Force -ErrorAction SilentlyContinue; Log "info" "Cleared Prefetch" } Catch { Log "warn" "Failed to clear Prefetch" }
}

# Example: attempt to stop/start service (best-effort)
Try {
    if (-not $dryrun) { Stop-Service -Name wuauserv -Force -ErrorAction SilentlyContinue; Log "info" "wuauserv stop attempted." }
    else { Log "info" "(DRY-RUN) Would stop wuauserv" }
} Catch { Log "warn" "Failed to stop wuauserv: $_" }

Try {
    if (-not $dryrun) { Start-Service -Name wuauserv -ErrorAction SilentlyContinue; Log "info" "wuauserv start attempted." }
    else { Log "info" "(DRY-RUN) Would start wuauserv" }
} Catch { Log "warn" "Failed to start wuauserv: $_" }

Log "info" "Cleanup completed."

if ($json -and $dryrun) {
    # Output JSON preview to stdout only in dry-run --json mode
    $out = @{ items = $previewItems }
    $jsonOut = $out | ConvertTo-Json -Depth 8
    # to avoid mixing with logs, write the JSON as the final output
    Write-Output $jsonOut
    exit 0
}

exit 0