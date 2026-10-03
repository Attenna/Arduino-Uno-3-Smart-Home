[CmdletBinding()]
param(
    [string]$HostName = "10.29.127.49",
    [string]$RemoteUser = "HwHiAiUser",
    [string]$Branch = "main"
)

$ErrorActionPreference = "Stop"
$repoRoot = (git rev-parse --show-toplevel).Trim()
if ($LASTEXITCODE -ne 0) { throw "Not inside a Git repository" }

$commit = (git -C $repoRoot rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0) { throw "Unable to resolve HEAD" }
$shortCommit = $commit.Substring(0, 12)
$bundlePath = Join-Path ([System.IO.Path]::GetTempPath()) "smarthome-$shortCommit.bundle"
$remoteBundle = "/tmp/smarthome-$shortCommit.bundle"
$target = "${RemoteUser}@${HostName}"

try {
    git -C $repoRoot bundle create $bundlePath $Branch
    if ($LASTEXITCODE -ne 0) { throw "Unable to create Git bundle" }

    scp -o StrictHostKeyChecking=accept-new `
        $bundlePath (Join-Path $repoRoot "scripts/sync_orangepi.sh") `
        "${target}:/tmp/"
    if ($LASTEXITCODE -ne 0) { throw "Unable to upload deployment files" }

    $uploadedScript = "/tmp/sync_orangepi.sh"
    ssh -o StrictHostKeyChecking=accept-new $target `
        "BUNDLE_PATH='$remoteBundle' BRANCH='$Branch' bash '$uploadedScript'"
    if ($LASTEXITCODE -ne 0) { throw "Orange Pi deployment failed" }

    Write-Output "Synchronized local, GitHub, and Orange Pi commit $commit"
}
finally {
    Remove-Item -LiteralPath $bundlePath -Force -ErrorAction SilentlyContinue
}
