#!/usr/bin/env bash
set -euo pipefail

if ! command -v planoai >/dev/null 2>&1; then
  echo "planoai non trovato. Installa Plano seguendo https://docs.planoai.dev/"
  exit 1
fi

planoai up config/plano.yaml
