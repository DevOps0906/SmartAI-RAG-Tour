# Tailwind v4 standalone CLI 로 app.css 빌드. 실행 파일: tools\bin\tailwindcss.exe (v4.1.18)
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
& "tools\bin\tailwindcss.exe" -i src/web/static/css/app.src.css -o src/web/static/css/app.css --minify @args
