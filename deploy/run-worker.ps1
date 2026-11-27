[CmdletBinding()]
param([string]$Python = 'python')
$ErrorActionPreference = 'Stop'
# Configure only worker variables in this session; the entry re-execs with an allowlist.
& $Python -B -m aiqa.hosted.worker
exit $LASTEXITCODE
