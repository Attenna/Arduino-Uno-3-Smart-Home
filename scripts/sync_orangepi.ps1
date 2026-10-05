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
$scriptPath = Join-Path ([System.IO.Path]::GetTempPath()) "sync_orangepi.sh"
$remoteBundle = "/tmp/smarthome-$shortCommit.bundle"
$target = "${RemoteUser}@${HostName}"

try {
    git -C $repoRoot bundle create $bundlePath $Branch
    if ($LASTEXITCODE -ne 0) { throw "Unable to create Git bundle" }

    # 远端只由 bash 执行：部署机 core.autocrlf=true 时工作区里的 .sh 是 CRLF，
    # 行尾的 CR 会被 bash 当成选项名的一部分，脚本第 2 行就退出（issue #16）。
    # 上传前规范化成 LF，部署结果就不再取决于部署机的换行设置。
    $scriptText = (Get-Content -Raw -LiteralPath (Join-Path $repoRoot "scripts/sync_orangepi.sh"))
    [System.IO.File]::WriteAllText($scriptPath, ($scriptText -replace "`r`n", "`n"))

    scp -o StrictHostKeyChecking=accept-new `
        $bundlePath $scriptPath `
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
    Remove-Item -LiteralPath $scriptPath -Force -ErrorAction SilentlyContinue
}
