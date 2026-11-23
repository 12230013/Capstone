$ProjectDir = Split-Path $PSScriptRoot -Parent
Set-Location $PSScriptRoot
& "$ProjectDir\.venv\Scripts\python.exe" -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8001 @args
