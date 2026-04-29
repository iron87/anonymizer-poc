import json
import os
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from presidio_analyzer import AnalyzerEngine
from presidio_analyzer.nlp_engine import NlpEngineProvider
from presidio_anonymizer import AnonymizerEngine
from presidio_anonymizer.entities import OperatorConfig

from src.common.models import (
    AnonymizeRequest,
    AnonymizeResponse,
    ChatSafeRequest,
    ChatSafeResponse,
    DeanonymizeRequest,
    DeanonymizeResponse,
    PresidioRequest,
    PresidioResponse,
)
from src.common.ollama_client import OllamaClient
from src.common.vault_store import SessionState, VaultStore

app = FastAPI(
    title="Anonymizer PoC",
    version="0.1.0",
    description="PII anonymization/deanonymization gateway for local LLM calls via Ollama.",
)

store = VaultStore()
ollama = OllamaClient()
default_model = os.getenv("DEFAULT_OLLAMA_MODEL", "llama3.2:latest")

# Shared Presidio engines — initialised once at startup (loads spaCy model)
_nlp_provider = NlpEngineProvider(nlp_configuration={
    "nlp_engine_name": "spacy",
    "models": [{"lang_code": "en", "model_name": "en_core_web_sm"}],
})
_analyzer = AnalyzerEngine(nlp_engine=_nlp_provider.create_engine())
_anonymizer_engine = AnonymizerEngine()


# ---------------------------------------------------------------------------
# Helper: Presidio-based reversible anonymisation
# ---------------------------------------------------------------------------

_ENTITY_TYPES = [
    "CREDIT_CARD", "EMAIL_ADDRESS", "IBAN_CODE", "IP_ADDRESS",
    "PERSON", "PHONE_NUMBER", "US_SSN",
]


def _do_anonymize(text: str, state: SessionState, language: str = "en") -> str:
    results = _analyzer.analyze(text=text, language=language, entities=_ENTITY_TYPES)
    # Sort by position descending so replacements don't shift offsets
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


@app.get("/", response_class=HTMLResponse)
async def home() -> str:
    return """
    <html>
        <head><title>Anonymizer PoC</title></head>
        <body style=\"font-family: sans-serif; margin: 2rem;\">
            <h1>Anonymizer PoC</h1>
            <p>Endpoints:</p>
            <ul>
                <li>POST /v1/anonymize</li>
                <li>POST /v1/deanonymize</li>
                <li>POST /v1/chat-safe</li>
                <li>POST /v1/presidio/anonymize</li>
                <li>GET /health</li>
            </ul>
        </body>
    </html>
    """


@app.get("/health")
async def health() -> dict:
    return {"ok": True, "stats": store.stats()}


@app.post("/v1/anonymize", response_model=AnonymizeResponse)
async def anonymize(req: AnonymizeRequest) -> AnonymizeResponse:
    session_id, state = store.get_or_create(req.session_id)
    anonymized_text = _do_anonymize(req.text, state, language=req.language)
    store.set_last_prompt(session_id, anonymized_text)
    has_pii = anonymized_text != req.text

    return AnonymizeResponse(
        session_id=session_id,
        anonymized_text=anonymized_text,
        is_valid=not has_pii,
        risk_score=1.0 if has_pii else 0.0,
    )


@app.post("/v1/deanonymize", response_model=DeanonymizeResponse)
async def deanonymize(req: DeanonymizeRequest) -> DeanonymizeResponse:
    state = store.get(req.session_id)
    if not state:
        raise HTTPException(status_code=404, detail="session_id not found")

    restored_text = _do_deanonymize(req.text, state)

    return DeanonymizeResponse(
        session_id=req.session_id,
        deanonymized_text=restored_text,
        is_valid=True,
        risk_score=0.0,
    )


@app.post("/v1/chat-safe", response_model=ChatSafeResponse)
async def chat_safe(req: ChatSafeRequest) -> ChatSafeResponse:
    session_id, state = store.get_or_create(req.session_id)

    anonymized_prompt = _do_anonymize(req.message, state, language=req.language)
    store.set_last_prompt(session_id, anonymized_prompt)

    model_name = req.model or default_model

    _DEFAULT_SYSTEM_PROMPT = (
        "You are a helpful assistant. "
        "The user's message may contain anonymized placeholders such as "
        "[REDACTED_PERSON_1], [REDACTED_EMAIL_ADDRESS_1], [REDACTED_PHONE_NUMBER_1], etc. "
        "These placeholders represent real values that have been redacted for privacy. "
        "Treat them as legitimate stand-ins and answer the request normally, "
        "keeping the placeholders intact in your response."
    )
    effective_system_prompt = req.system_prompt or _DEFAULT_SYSTEM_PROMPT

    raw_output = await ollama.chat(
        model=model_name,
        user_message=anonymized_prompt,
        system_prompt=effective_system_prompt,
    )

    final_output = _do_deanonymize(raw_output, state)

    return ChatSafeResponse(
        session_id=session_id,
        model=model_name,
        anonymized_prompt=anonymized_prompt,
        raw_model_output=raw_output,
        final_output=final_output,
    )


# ---------------------------------------------------------------------------
# Plano filter endpoints — used by Plano's input_filters / output_filters
# ---------------------------------------------------------------------------

@app.post("/anonymize/{path:path}")
async def plano_anonymize(path: str, request: Request) -> dict:
    """Input filter: anonymize PII in all user messages before they reach the LLM."""
    request_id = request.headers.get("x-request-id") or str(uuid4())
    body = await request.json()
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

    return body


@app.post("/deanonymize/{path:path}")
async def plano_deanonymize(path: str, request: Request) -> Response:
    """Output filter: restore original PII in the LLM response (SSE or full JSON)."""
    request_id = request.headers.get("x-request-id", "unknown")
    raw = await request.body()
    state = store.get(request_id)
    if not state or not state.vault:
        return Response(content=raw, media_type="application/json")

    body_str = raw.decode("utf-8", errors="replace")

    if "data: " in body_str or "event: " in body_str:
        # SSE streaming response
        lines = []
        for line in body_str.split("\n"):
            stripped = line.strip()
            if stripped.startswith("data: ") and stripped[6:] != "[DONE]":
                try:
                    chunk = json.loads(stripped[6:])
                    for choice in chunk.get("choices", []):
                        delta = choice.get("delta", {})
                        if isinstance(delta.get("content"), str):
                            delta["content"] = _do_deanonymize(delta["content"], state)
                    lines.append("data: " + json.dumps(chunk))
                except json.JSONDecodeError:
                    lines.append(line)
            else:
                lines.append(line)
        return Response(content="\n".join(lines), media_type="text/plain")

    # Non-streaming full JSON
    try:
        body = json.loads(body_str)
        for choice in body.get("choices", []):
            msg = choice.get("message", {})
            if isinstance(msg.get("content"), str):
                msg["content"] = _do_deanonymize(msg["content"], state)
        return Response(content=json.dumps(body), media_type="application/json")
    except json.JSONDecodeError:
        return Response(content=raw, media_type="application/json")


@app.post("/v1/presidio/anonymize", response_model=PresidioResponse)
async def presidio_anonymize(req: PresidioRequest) -> PresidioResponse:
    try:
        analyzer = _analyzer
        anonymizer = _anonymizer_engine
        results = analyzer.analyze(text=req.text, language="en")
        operators = {
            "DEFAULT": OperatorConfig("replace", {"new_value": "<REDACTED>"}),
        }
        anonymized_result = anonymizer.anonymize(
            text=req.text,
            analyzer_results=results,
            operators=operators,
        )

        entities = [
            {
                "entity_type": item.entity_type,
                "start": item.start,
                "end": item.end,
                "score": item.score,
            }
            for item in results
        ]

        return PresidioResponse(
            anonymized_text=anonymized_result.text,
            entities=entities,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=(
                "Presidio pipeline failed. Ensure NLP model dependencies are installed. "
                f"Original error: {exc}"
            ),
        ) from exc
