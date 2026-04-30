import gzip
import json
import logging
import os
import zlib
from uuid import uuid4

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response
from presidio_analyzer import AnalyzerEngine
from presidio_analyzer.nlp_engine import NlpEngineProvider

from src.common.models import AgentViaPlanoRequest, AgentViaPlanoResponse
from src.common.vault_store import SessionState, VaultStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="Anonymizer PoC", version="0.1.0")

store = VaultStore()
plano_base_url = os.getenv("PLANO_BASE_URL", "http://localhost:12000")

_nlp_provider = NlpEngineProvider(nlp_configuration={
    "nlp_engine_name": "spacy",
    "models": [{"lang_code": "en", "model_name": "en_core_web_sm"}],
})
_analyzer = AnalyzerEngine(nlp_engine=_nlp_provider.create_engine())

_ENTITY_TYPES = [
    "CREDIT_CARD", "EMAIL_ADDRESS", "IBAN_CODE", "IP_ADDRESS",
    "PERSON", "PHONE_NUMBER", "US_SSN",
]

# Accumulates raw (possibly gzip) bytes across multiple filter calls for the same request.
# Plano may split a single gzip stream over two consecutive HTTP calls.
_raw_buffers: dict[str, bytes] = {}

# Partial placeholder buffers for SSE streaming, keyed by request_id.
_stream_buffers: dict[str, str] = {}


def _do_anonymize(text: str, state: SessionState, language: str = "en") -> str:
    results = _analyzer.analyze(text=text, language=language, entities=_ENTITY_TYPES)
    results = sorted(results, key=lambda r: r.start, reverse=True)
    out = text
    for item in results:
        original = text[item.start:item.end]
        if original in state.reverse:
            placeholder = state.reverse[original]
        else:
            count = state.counters.get(item.entity_type, 0) + 1
            state.counters[item.entity_type] = count
            placeholder = f"[REDACTED_{item.entity_type}_{count}]"
            state.vault[placeholder] = original
            state.reverse[original] = placeholder
        out = out[:item.start] + placeholder + out[item.end:]
    return out


def _do_deanonymize(text: str, state: SessionState) -> str:
    result = text
    for placeholder, original in state.vault.items():
        result = result.replace(placeholder, original)
    return result


def _deep_deanonymize(value, state: SessionState):
    if isinstance(value, str):
        return _do_deanonymize(value, state)
    if isinstance(value, list):
        return [_deep_deanonymize(item, state) for item in value]
    if isinstance(value, dict):
        return {k: _deep_deanonymize(v, state) for k, v in value.items()}
    return value


def _resolve_state(request_id: str, body_str: str) -> SessionState | None:
    state = store.get(request_id)
    if state and state.vault:
        return state
    # Fallback: find the vault whose placeholders appear in the body.
    best_state: SessionState | None = None
    best_hits = 0
    for _, candidate in store.items():
        if not candidate.vault:
            continue
        hits = sum(1 for p in candidate.vault if p in body_str)
        if hits > best_hits:
            best_hits = hits
            best_state = candidate
    return best_state if best_hits > 0 else None


def _restore_streaming_chunk(request_id: str, content: str, state: SessionState) -> str:
    combined = _stream_buffers.get(request_id, "") + content
    restored = _do_deanonymize(combined, state)
    last_open = restored.rfind("[")
    if last_open != -1 and "]" not in restored[last_open:]:
        _stream_buffers[request_id] = restored[last_open:]
        return restored[:last_open]
    _stream_buffers.pop(request_id, None)
    return restored


@app.get("/health")
async def health() -> dict:
    return {"ok": True, "sessions": store.stats()["sessions"]}


@app.post("/v1/agent/chat", response_model=AgentViaPlanoResponse)
async def agent_chat(req: AgentViaPlanoRequest) -> AgentViaPlanoResponse:
    request_id = req.session_id or str(uuid4())

    payload = {
        "model": req.model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a helpful assistant. "
                    "The user's message may contain anonymized placeholders such as "
                    "[REDACTED_PERSON_1], [REDACTED_EMAIL_ADDRESS_1], [REDACTED_PHONE_NUMBER_1], etc. "
                    "These placeholders represent real values that have been redacted for privacy. "
                    "Treat them as legitimate stand-ins and answer the request normally, "
                    "keeping all placeholder tokens exactly as-is in your response."
                ),
            },
            {"role": "user", "content": req.message},
        ],
        "stream": False,
        "user": request_id,
    }

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{plano_base_url}/v1/chat/completions",
                json=payload,
                headers={"x-request-id": request_id},
            )
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Plano unreachable: {exc}") from exc

    data = response.json()
    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")

    return AgentViaPlanoResponse(
        request_id=request_id,
        model=data.get("model", req.model),
        content=content,
        upstream=plano_base_url,
    )


# ---------------------------------------------------------------------------
# Plano filter endpoints
# ---------------------------------------------------------------------------

@app.post("/anonymize/{path:path}")
async def plano_anonymize(path: str, request: Request) -> dict:
    body = await request.json()
    request_id = request.headers.get("x-request-id") or body.get("user") or "unknown"
    _, state = store.get_or_create(request_id)

    messages = body.get("messages", [])
    if messages:
        modified = [
            {**msg, "content": _do_anonymize(msg["content"], state)}
            if msg.get("role") == "user" and isinstance(msg.get("content"), str)
            else msg
            for msg in messages
        ]
        body = {**body, "messages": modified}

    logger.info("[ANONYMIZE] request_id=%s vault=%s", request_id, state.vault)
    return body


@app.post("/deanonymize/{path:path}")
async def plano_deanonymize(path: str, request: Request) -> Response:
    request_id = request.headers.get("x-request-id", "unknown")
    raw = await request.body()

    # Plano sends gzip-compressed responses to the filter, split over two HTTP calls
    # (incomplete stream first, then the gzip footer). Accumulate and decompress.
    came_from_gzip = False
    if raw[:2] == b"\x1f\x8b":
        _raw_buffers[request_id] = raw
    elif request_id in _raw_buffers:
        _raw_buffers[request_id] += raw

    if request_id in _raw_buffers:
        try:
            body_bytes = zlib.decompress(_raw_buffers[request_id], wbits=47)
            del _raw_buffers[request_id]
            came_from_gzip = True
        except zlib.error:
            logger.info("[DEANONYMIZE] request_id=%s gzip incomplete, buffering", request_id)
            return Response(content=b"", media_type="application/json")
    else:
        body_bytes = raw

    body_str = body_bytes.decode("utf-8", errors="replace")
    state = _resolve_state(request_id, body_str)
    if not state or not state.vault:
        logger.warning("[DEANONYMIZE] request_id=%s no vault found, passing through", request_id)
        return Response(content=body_bytes, media_type="application/json")

    logger.info("[DEANONYMIZE] request_id=%s vault=%s", request_id, state.vault)

    # SSE / streaming response
    if "data: " in body_str or "event: " in body_str:
        lines = []
        for line in body_str.split("\n"):
            stripped = line.strip()
            if stripped.startswith("data: ") and stripped[6:] != "[DONE]":
                try:
                    chunk = json.loads(stripped[6:])
                    for choice in chunk.get("choices", []):
                        delta = choice.get("delta", {})
                        if isinstance(delta.get("content"), str):
                            delta["content"] = _restore_streaming_chunk(request_id, delta["content"], state)
                        msg = choice.get("message", {})
                        if isinstance(msg.get("content"), str):
                            msg["content"] = _restore_streaming_chunk(request_id, msg["content"], state)
                    lines.append("data: " + json.dumps(chunk))
                except json.JSONDecodeError:
                    lines.append(line)
            else:
                lines.append(line)
        return Response(content="\n".join(lines), media_type="text/plain")

    # Non-streaming full JSON
    try:
        result_bytes = json.dumps(_deep_deanonymize(json.loads(body_str), state)).encode("utf-8")
        if came_from_gzip:
            result_bytes = gzip.compress(result_bytes)
        return Response(content=result_bytes, media_type="application/json")
    except json.JSONDecodeError:
        return Response(content=body_bytes, media_type="application/json")
