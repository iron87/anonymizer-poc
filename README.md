# Anonymizer PoC for LLM Calls (Plano + Ollama)

A sample repository showing how to anonymize sensitive data before LLM calls,
with reversible deanonymization of the final response.

Pipeline:

1. User input containing PII
2. Anonymization (LLM Guard + Vault)
3. Local LLM call via Ollama
4. Deanonymization of the output

Includes an extra comparison endpoint using Microsoft Presidio.

## Stack

- FastAPI web server
- [LLM Guard](https://github.com/protectai/llm-guard) for reversible anonymize/deanonymize
- [Microsoft Presidio](https://github.com/microsoft/presidio) for de-identification comparison
- [Ollama](https://github.com/ollama/ollama) for local LLM inference
- [Plano](https://github.com/katanemo/plano) for agent orchestration and proxy

## Project structure

- `src/api/main.py`: main API endpoints
- `src/common/vault_store.py`: session management and vault for deanonymization
- `src/common/ollama_client.py`: local Ollama HTTP client
- `config/plano.yaml`: Plano listener/agent configuration
- `scripts/demo.sh`: end-to-end demo curl calls

## Prerequisites

- Python 3.11+
- Ollama running locally at `http://localhost:11434`
- A local model pulled, e.g.:

```bash
ollama pull llama3.2:latest
```

## Run the API locally

```bash
chmod +x scripts/run_api.sh
./scripts/run_api.sh
```

Server available at `http://localhost:9000`.

## Endpoints

### POST `/v1/anonymize`

Anonymizes a text and stores the PII mapping in the session vault.

### POST `/v1/deanonymize`

Restores placeholders in a text using the session vault.

### POST `/v1/chat-safe`

Runs the full privacy-safe pipeline:
- anonymize the input
- call Ollama `/api/chat`
- deanonymize the output

### POST `/v1/presidio/anonymize`

Comparison endpoint using Presidio (`<REDACTED>` replacement).

## Quick demo

```bash
chmod +x scripts/demo.sh
./scripts/demo.sh
```

## Using with Plano

### Option A: Plano installed locally

```bash
chmod +x scripts/run_plano.sh
./scripts/run_plano.sh
```

Plano listener on `http://localhost:8001` with the `safe_chat_agent` routing to the web server on `:9000`.

### Option B: Docker Compose

```bash
docker compose up --build
```

Starts:
- FastAPI app on `:9000`
- Plano on `:8001`

## cURL example — `chat-safe`

```bash
curl http://localhost:9000/v1/chat-safe \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "test-1",
    "model": "llama3.2:latest",
    "message": "Hi, I am Mario Rossi, email mario.rossi@example.com"
  }'
```

Response includes:
- `anonymized_prompt`
- `raw_model_output`
- `final_output` (deanonymized)

## Notes

- LLM Guard downloads NER model assets on first run.
- Presidio may require additional NLP dependencies depending on your configuration.
- This PoC uses an in-memory vault (non-persistent). For production use a secure, encrypted storage backend.
