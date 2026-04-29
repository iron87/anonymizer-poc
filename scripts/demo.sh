#!/usr/bin/env bash
set -euo pipefail

SESSION_ID="demo-session-1"

echo "1) Anonymize"
curl -s http://localhost:9000/v1/anonymize \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "'"$SESSION_ID"'",
    "text": "Please contact Mario Rossi at mario.rossi@example.com or 3331234567 regarding the project kickoff meeting."
  }' | jq .

echo "2) Safe chat"
curl -s http://localhost:9000/v1/chat-safe \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "'"$SESSION_ID"'",
    "model": "llama3.2:latest",
    "message": "Rewrite this as a short professional reminder while keeping all contact details unchanged: contact Mario Rossi at mario.rossi@example.com or 3331234567 regarding the project kickoff meeting."
  }' | jq .
