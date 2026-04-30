#!/usr/bin/env bash
set -euo pipefail

SESSION_ID="demo-session-$(date +%s)"

echo "Agent -> Plano -> filters -> LLM"
curl --max-time 60 -s http://localhost:9000/v1/agent/chat \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "'"$SESSION_ID"'",
    "model": "local/llama3.2",
    "message": "Please rewrite this reminder in a professional tone and keep all contact details unchanged: Project kickoff is tomorrow at 10:00. Contact mario.rossi@example.com or 3331234567 for questions."
  }' | jq .
