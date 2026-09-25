#!/usr/bin/env bash
set -euo pipefail

if [ "${DEMO_MODE:-0}" = "1" ]; then
  python -m tools.reset_demo
  python -m tools.issuer \
    --manufacturer-id MFG001 \
    --manufacturer-name "AgroSafe Industries" \
    --product-id PROD001 \
    --product-name "CropShield Fungicide 250SC" \
    --batch B24A001 \
    --expiry 2026-12-31 \
    --active-ingredient-class strobilurin \
    --registration-number REG-AG-2024-001 \
    --count 1 \
    --host "${HOST:-http://localhost:8000}" >/tmp/agroguard-issued-code.txt
fi

exec uvicorn server.main:app --host 0.0.0.0 --port "${PORT:-8000}"
