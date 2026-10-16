#!/usr/bin/env bash
# Tailwind v4 standalone CLI 로 app.css 빌드. 실행 파일: tools/bin/tailwindcss(.exe), 버전 v4.1.18
set -euo pipefail
cd "$(dirname "$0")/.."
BIN=tools/bin/tailwindcss
[ -x "$BIN" ] || BIN=tools/bin/tailwindcss.exe
"$BIN" -i src/web/static/css/app.src.css -o src/web/static/css/app.css --minify "$@"
