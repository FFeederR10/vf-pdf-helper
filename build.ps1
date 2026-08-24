$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$ProductName = "VF PDF Helper"
$DistRoot = Join-Path $ProjectRoot "dist"
$ProductDir = Join-Path $DistRoot $ProductName
$ArchivePath = Join-Path $DistRoot "VF-PDF-Helper-windows-x64.zip"
$BuildRoot = Join-Path $ProjectRoot "build"
$NanoPrcDll = Join-Path $ProjectRoot ".venv\Lib\site-packages\bin\nano_prc.dll"
$NumPyLicense = Get-ChildItem -Path (Join-Path $ProjectRoot ".venv\Lib\site-packages\numpy-*.dist-info\licenses\LICENSE.txt") -File | Select-Object -First 1

if (-not (Test-Path -LiteralPath $Python)) {
    throw "Missing .venv. Create it and install requirements.txt first."
}
if (-not (Test-Path -LiteralPath $NanoPrcDll)) {
    throw "Missing nanoPRC runtime DLL. Install requirements.txt before building."
}
if (-not $NumPyLicense) {
    throw "Missing NumPy license file. Install requirements.txt before building."
}

& $Python (Join-Path $ProjectRoot "scripts\make_icon.py")

& $Python -m PyInstaller `
    --noconfirm `
    --clean `
    --onedir `
    --windowed `
    --name $ProductName `
    --icon (Join-Path $ProjectRoot "assets\vf-pdf-helper.ico") `
    --add-data "$ProjectRoot\assets\vf-pdf-helper.ico:assets" `
    --add-binary "${NanoPrcDll}:." `
    --hidden-import nanoprc_py._core `
    --version-file (Join-Path $ProjectRoot "version_info.txt") `
    --distpath $DistRoot `
    --workpath (Join-Path $BuildRoot "pyinstaller") `
    --specpath $BuildRoot `
    (Join-Path $ProjectRoot "main.py")

if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed with exit code $LASTEXITCODE."
}

Copy-Item -LiteralPath (Join-Path $ProjectRoot "LICENSE") -Destination $ProductDir -Force
Copy-Item -LiteralPath (Join-Path $ProjectRoot "THIRD_PARTY_NOTICES.md") -Destination $ProductDir -Force
Copy-Item -LiteralPath (Join-Path $ProjectRoot "SOURCE_OFFER.md") -Destination $ProductDir -Force
Copy-Item -LiteralPath (Join-Path $ProjectRoot "licenses") -Destination $ProductDir -Recurse -Force
Copy-Item -LiteralPath $NumPyLicense.FullName -Destination (Join-Path $ProductDir "licenses\NumPy-LICENSE.txt") -Force

if (Test-Path -LiteralPath $ArchivePath) {
    Remove-Item -LiteralPath $ArchivePath -Force
}
Compress-Archive -Path (Join-Path $ProductDir "*") -DestinationPath $ArchivePath -CompressionLevel Optimal

Write-Host ""
Write-Host "Build completed:" -ForegroundColor Green
Write-Host (Join-Path $ProductDir "$ProductName.exe")
Write-Host $ArchivePath
