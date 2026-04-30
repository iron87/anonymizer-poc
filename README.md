# Anonymizer PoC for LLM Calls (Plano + Ollama)

A PoC that automatically anonymizes PII before LLM calls and deanonymizes
placeholders in the final response. The agent sends requests through Plano's
model-listener filter chain, which handles anonymization/deanonymization
transparently.

## Architecture

```
Client
  └─► POST /v1/agent/chat  (FastAPI :9000)
    └─► Plano :12000  (receives OpenAI-compatible request)
              ├─ input filter → POST /anonymize/{path}  (FastAPI :9000)
              │     └─ Presidio detects PII, replaces with placeholders, stores vault
              ├─► Ollama :11434  (model inference on anonymized prompt)
              └─ output filter → POST /deanonymize/{path}  (FastAPI :9000)
                    └─ Vault looked up by request_id, placeholders restored
        └─► Client receives original PII in response
```

The **vault** is an in-memory map (`request_id → {placeholder: original_value}`)
held in FastAPI and correlated via the `x-request-id` header / `user` field.

### Gzip Buffering

Ollama compresses HTTP responses with gzip (standard HTTP content-encoding).
Plano forwards these bytes to the output filter, but splits the gzip stream over
**two separate HTTP calls** — an incomplete chunk followed by the gzip footer
(e.g. 229 bytes then 10 bytes). The deanonymize filter buffers the raw bytes and
decompresses only once the complete stream is available, then re-compresses the
modified response before returning it to Plano.

## Stack

- FastAPI + Uvicorn (port 9000)
- Microsoft Presidio (`presidio-analyzer`) + spaCy `en_core_web_sm`
- Plano model listener with HTTP input/output filters (port 12000)
- Ollama (`llama3.2:latest`) on port 11434

Detected PII entity types: `CREDIT_CARD`, `EMAIL_ADDRESS`, `IBAN_CODE`,
`IP_ADDRESS`, `PERSON`, `PHONE_NUMBER`, `US_SSN`.

## Project Structure

```
src/
  api/main.py              # FastAPI app: agent endpoint + Plano filter endpoints
  common/
    vault_store.py         # In-memory vault (placeholder ↔ original value)
    models.py              # Pydantic request/response models
config/
  plano.yaml               # Plano model-listener config (port 12000, filter chain)
scripts/
  demo.sh                  # End-to-end demo
  run_api.sh               # Run FastAPI locally
  run_plano.sh             # Run Plano locally (requires planoai)
```

## Prerequisites

- Docker + Docker Compose
- Ollama running at `http://localhost:11434` with the model pulled:

```bash
ollama pull llama3.2:latest
```

## Run With Docker Compose

```bash
docker compose up --build -d
```

Services:

| Service | URL |
|---------|-----|
| FastAPI | `http://localhost:9000` |
| Plano model listener | `http://localhost:12000` |

## Endpoints

### Agent Endpoint

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/agent/chat` | Agent → Plano filter chain → Ollama |
| `GET` | `/health` | Health check |

### Plano Filter Endpoints (called by Plano internally)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/anonymize/{path}` | Input filter: anonymize user messages |
| `POST` | `/deanonymize/{path}` | Output filter: restore placeholders in response |

### Request / Response

`POST /v1/agent/chat`

```json
// Request
{
  "session_id": "my-session-123",
  "model": "local/llama3.2",
  "message": "Contact mario.rossi@example.com or 3331234567 for info."
}

// Response
{
  "request_id": "my-session-123",
  "model": "llama3.2",
  "content": "You can reach out to mario.rossi@example.com or call 3331234567.",
  "upstream": "http://plano:12000"
}
```

The model name sent to the agent endpoint must match the model configured in
`config/plano.yaml` (`local/llama3.2`). Plano resolves `local/` to the Ollama
provider.

## Quick Test

```bash
curl --max-time 60 -s http://localhost:9000/v1/agent/chat \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "test-1",
    "model": "local/llama3.2",
    "message": "Please rewrite this reminder in a professional tone, keeping all contact details unchanged: Project kickoff is tomorrow at 10:00. Contact mario.rossi@example.com or 3331234567 for questions."
  }' | jq .
```

## Notes

- Vault storage is in-memory and process-scoped. Restarting FastAPI clears all vaults.
- For production, replace the in-memory vault with encrypted persistent storage.
- The system prompt injected by the agent instructs the LLM to treat placeholders as legitimate stand-ins and keep them intact in its response.
