$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
py -m unittest discover -s tests -v
py -m jobfit demo
Start-Process (Resolve-Path "site\index.html")
