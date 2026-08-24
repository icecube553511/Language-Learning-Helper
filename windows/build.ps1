$ErrorActionPreference = "Stop"

$windowsDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$rootDir = Split-Path -Parent $windowsDir
$catalogDir = Join-Path $rootDir "shared\content"

Set-Location -LiteralPath $rootDir

python -m unittest discover -s ".\windows\tests" -v
if ($LASTEXITCODE -ne 0) {
    throw "Windows tests failed with exit code $LASTEXITCODE"
}

$arguments = @(
    "-m", "PyInstaller",
    "--noconfirm",
    "--clean",
    "--onefile",
    "--windowed",
    "--name", "LexiTrack",
    "--manifest", (Join-Path $windowsDir "app.manifest"),
    "--paths", $windowsDir,
    "--distpath", (Join-Path $windowsDir "dist"),
    "--workpath", (Join-Path $windowsDir "build"),
    "--specpath", $windowsDir,
    (Join-Path $windowsDir "main.py")
)

if (Test-Path -LiteralPath $catalogDir) {
    $arguments += @("--add-data", "$catalogDir;shared\content")
}

python @arguments
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed with exit code $LASTEXITCODE"
}

$generatedSpec = Join-Path $windowsDir "LexiTrack.spec"
if (Test-Path -LiteralPath $generatedSpec) {
    Remove-Item -LiteralPath $generatedSpec -Force
}

Write-Host "Build complete: $windowsDir\dist\LexiTrack.exe"
