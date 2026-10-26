$ErrorActionPreference = "Stop"

$engineDirectory = Join-Path $PSScriptRoot "engine"
$archivePath = Join-Path $engineDirectory "proxy-scraper-checker-build-3872.zip"
$releaseApi = "https://api.github.com/repos/monosans/proxy-scraper-checker/releases/tags/build-3872"
$assetName = "proxy-scraper-checker-binary-x86_64-pc-windows-msvc.zip"

New-Item -ItemType Directory -Force -Path $engineDirectory | Out-Null
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

try {
    $release = Invoke-RestMethod -Uri $releaseApi -Headers @{
        Accept = "application/vnd.github+json"
        "User-Agent" = "ProxyScout"
    } -TimeoutSec 30
    if ($release.tag_name -ne "build-3872") {
        throw "GitHub returned an unexpected release tag."
    }

    $asset = $release.assets | Where-Object { $_.name -eq $assetName } | Select-Object -First 1
    if (-not $asset) {
        throw "The pinned release does not contain the expected x64 Windows archive: $assetName"
    }
    $assetUri = [Uri]$asset.browser_download_url
    if ($assetUri.Scheme -ne "https" -or $assetUri.Host -ne "github.com") {
        throw "GitHub returned an unexpected download host."
    }

    Invoke-WebRequest -Uri $assetUri.AbsoluteUri -OutFile $archivePath -UseBasicParsing -TimeoutSec 120
    Expand-Archive -LiteralPath $archivePath -DestinationPath $engineDirectory -Force
}
finally {
    if (Test-Path -LiteralPath $archivePath -PathType Leaf) {
        Remove-Item -LiteralPath $archivePath -Force
    }
}

$binaryPath = Join-Path $engineDirectory "proxy-scraper-checker.exe"
if (-not (Test-Path -LiteralPath $binaryPath -PathType Leaf)) {
    throw "The pinned release archive did not contain proxy-scraper-checker.exe. Check the release page and platform archive."
}

Write-Output "Installed checker: $binaryPath"
