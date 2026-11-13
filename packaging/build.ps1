param([Parameter(Mandatory=$true)][string]$InnoCompiler)
$ErrorActionPreference='Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
python -m pip install -r requirements-lock.txt
if($LASTEXITCODE -ne 0){throw 'Dependency installation failed'}
python packaging/collect_licenses.py
if($LASTEXITCODE -ne 0){throw 'License collection failed'}
python packaging/verify_licenses.py
if($LASTEXITCODE -ne 0){throw 'Project license verification failed'}
python -m unittest discover -s tests -v
if($LASTEXITCODE -ne 0){throw 'Tests failed'}
python -m PyInstaller --noconfirm packaging/veylfit.spec
if($LASTEXITCODE -ne 0){throw 'Application build failed'}
python packaging/verify_licenses.py --bundle dist/Veylfit/_internal
if($LASTEXITCODE -ne 0){throw 'Bundled license verification failed'}
& $InnoCompiler packaging/installer.iss
if($LASTEXITCODE -ne 0){throw 'Installer build failed'}
Get-FileHash release/*.exe -Algorithm SHA256
