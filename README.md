# Anonymizer PoC for LLM Calls (Plano + Ollama)

A PoC that anonymizes PII before LLM calls and deanonymizes placeholders in the
final response.

Current architecture:

1. Client sends a request to Plano (`:12000`)
2. Plano input filter calls FastAPI `/anonymize/{path}`
3. Plano forwards the sanitized request to Ollama
4. Plano output filter calls FastAPI `/deanonymize/{path}`
5. Client receives restored output

FastAPI also exposes direct endpoints (`/v1/*`) for standalone testing.

## Stack

- FastAPI
- Microsoft Presidio (`presidio-analyzer`, `presidio-anonymizer`)
- spaCy `en_core_web_sm`
- Ollama (`llama3.2:latest`)
- Plano model listener with HTTP input/output filters

## Project Structure

- `src/api/main.py`: API and filter endpoints
- `src/common/vault_store.py`: in-memory session vault (placeholder <-> original)
- `src/common/ollama_client.py`: Ollama HTTP client
- `config/plano.yaml`: Plano model-listener config
- `scripts/demo.sh`: direct FastAPI demo
- `scripts/run_api.sh`: run FastAPI locally
- `scripts/run_plano.sh`: run Plano locally (`planoai` required)

## Prerequisites

- Docker + Docker Compose, or Python 3.11+ for local run
- Ollama running at `http://localhost:11434`
- Model available locally:

```bash
ollama pull llama3.2:latest
```

## Run With Docker Compose (Recommended)

```bash
docker compose up --build -d
```

Services:

- FastAPI: `http://localhost:9000`
- Plano model listener: `http://localhost:12000`

## Run Locally (Without Docker)

Terminal 1:

```bash
chmod +x scripts/run_api.sh
./scripts/run_api.sh
```

Terminal 2 (requires `planoai` installed):

```bash
chmod +x scripts/run_plano.sh
./scripts/run_plano.sh
```

## Endpoints

Direct API endpoints (FastAPI):

- `POST /v1/anonymize`
- `POST /v1/deanonymize`
- `POST /v1/chat-safe`
- `POST /v1/presidio/anonymize`

Plano filter endpoints (called by Plano, not by end users):

- `POST /anonymize/{path}`
- `POST /deanonymize/{path}`

## Quick Demo (FastAPI Direct)

```bash
chmod +x scripts/demo.sh
./scripts/demo.sh
```

The demo shows:

- anonymized input with typed placeholders
- model output on placeholders
- final deanonymized output

## End-to-End Through Plano

```bash
curl -s http://localhost:12000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "local/llama3.2",
    "messages": [{
      "role": "user",
      "content": "Rewrite this reminder and keep contacts: email mario.rossi@example.com phone 3331234567"
    }],
    "stream": false
  }' | jq .
```

## Notes

- No `llm-guard` dependency is used in this project.
- Vault storage is in-memory and session-scoped.
- For production, use encrypted persistent storage for mappings.
