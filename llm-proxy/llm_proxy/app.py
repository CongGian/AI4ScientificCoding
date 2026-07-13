from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any

import asyncpg
import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

UPSTREAM_BASE_URL = os.environ.get("LLM_UPSTREAM_BASE_URL", "https://llm.jetstream-cloud.org/v1").rstrip("/")
UPSTREAM_API_KEY = os.environ.get("LLM_UPSTREAM_API_KEY", "")
GATEWAY_SIGNING_KEY = os.environ.get("LLM_GATEWAY_SIGNING_KEY", "")
DEPLOYMENT_ID = os.environ.get("LLM_DEPLOYMENT_ID", "staging")
CONSENT_VERSION = os.environ.get("LLM_CONSENT_VERSION", "unspecified")
CAPTURE_CONTENT = os.environ.get("LLM_CAPTURE_CONTENT", "true").lower() not in {"0", "false", "no"}
MAX_CAPTURE_BYTES = int(os.environ.get("LLM_MAX_CAPTURE_BYTES", "10485760"))
LOGGING_FAILURE_POLICY = os.environ.get("LLM_LOGGING_FAILURE_POLICY", "deny").lower()

POSTGRES_HOST = os.environ.get("POSTGRES_HOST", "interaction-db")
POSTGRES_PORT = int(os.environ.get("POSTGRES_PORT", "5432"))
POSTGRES_DB = os.environ.get("POSTGRES_DB", "llm_research")
POSTGRES_USER = os.environ.get("POSTGRES_USER", "llm_gateway")
POSTGRES_PASSWORD = os.environ.get("POSTGRES_PASSWORD", "")

app = FastAPI(title="AI4ScientificCoding Central LLM Gateway")
client = httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=30.0))
pool: asyncpg.Pool | None = None


CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS llm_interactions (
    interaction_id uuid PRIMARY KEY,
    participant_id text NOT NULL,
    deployment_id text NOT NULL,
    consent_version text NOT NULL,
    client_name text,
    request_started_at timestamptz NOT NULL,
    request_completed_at timestamptz NOT NULL,
    status text NOT NULL,
    upstream_status integer,
    method text NOT NULL,
    path text NOT NULL,
    query text,
    model_requested text,
    model_returned text,
    duration_ms double precision NOT NULL,
    prompt_tokens integer,
    completion_tokens integer,
    total_tokens integer,
    request_payload jsonb,
    response_payload jsonb,
    request_truncated boolean NOT NULL DEFAULT false,
    response_truncated boolean NOT NULL DEFAULT false,
    capture_content boolean NOT NULL DEFAULT true,
    error text,
    created_at timestamptz NOT NULL DEFAULT now()
);
"""


INSERT_INTERACTION_SQL = """
INSERT INTO llm_interactions (
    interaction_id,
    participant_id,
    deployment_id,
    consent_version,
    client_name,
    request_started_at,
    request_completed_at,
    status,
    upstream_status,
    method,
    path,
    query,
    model_requested,
    model_returned,
    duration_ms,
    prompt_tokens,
    completion_tokens,
    total_tokens,
    request_payload,
    response_payload,
    request_truncated,
    response_truncated,
    capture_content,
    error
) VALUES (
    $1, $2, $3, $4, $5, $6, $7, $8, $9, $10,
    $11, $12, $13, $14, $15, $16, $17, $18,
    $19::jsonb, $20::jsonb, $21, $22, $23, $24
);
"""


def _database_dsn() -> str:
    return (
        f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}"
        f"@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"
    )


async def _create_pool_with_retries() -> asyncpg.Pool:
    last_error: Exception | None = None
    for _ in range(30):
        try:
            db_pool = await asyncpg.create_pool(dsn=_database_dsn(), min_size=1, max_size=10)
            async with db_pool.acquire() as conn:
                await conn.execute(CREATE_TABLE_SQL)
            return db_pool
        except Exception as exc:  # pragma: no cover - depends on database boot timing
            last_error = exc
            await asyncio_sleep(2)
    raise RuntimeError(f"Could not connect to PostgreSQL: {last_error}") from last_error


async def asyncio_sleep(seconds: float) -> None:
    import asyncio

    await asyncio.sleep(seconds)


@app.on_event("startup")
async def _startup() -> None:
    global pool
    if not POSTGRES_PASSWORD:
        raise RuntimeError("POSTGRES_PASSWORD is required")
    if not GATEWAY_SIGNING_KEY:
        raise RuntimeError("LLM_GATEWAY_SIGNING_KEY is required")
    pool = await _create_pool_with_retries()


@app.on_event("shutdown")
async def _shutdown() -> None:
    await client.aclose()
    if pool is not None:
        await pool.close()


@app.get("/")
async def healthcheck() -> dict[str, str]:
    return {"status": "ok", "upstream": UPSTREAM_BASE_URL, "deployment_id": DEPLOYMENT_ID}


@app.get("/ready")
async def ready() -> dict[str, str]:
    if pool is None:
        return JSONResponse({"status": "not_ready"}, status_code=503)  # type: ignore[return-value]
    async with pool.acquire() as conn:
        await conn.fetchval("SELECT 1")
    return {"status": "ready"}


def _decode_json_or_text(raw: bytes) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return raw.decode("utf-8", errors="replace")


def _decode_sse(raw: bytes) -> dict[str, list[Any]]:
    events: list[Any] = []
    for line in raw.decode("utf-8", errors="replace").splitlines():
        if not line.startswith("data:"):
            continue
        data = line.removeprefix("data:").strip()
        if not data or data == "[DONE]":
            continue
        try:
            events.append(json.loads(data))
        except json.JSONDecodeError:
            events.append(data)
    return {"events": events}


def _capture_payload(
    raw: bytes,
    content_type: str,
    max_bytes: int,
    capture_content: bool,
) -> tuple[Any, bool]:
    if not capture_content:
        return {"_capture_disabled": True}, False

    truncated = len(raw) > max_bytes
    captured = raw[:max_bytes]
    if "text/event-stream" in content_type.lower():
        payload = _decode_sse(captured)
    else:
        payload = _decode_json_or_text(captured)

    if truncated:
        if isinstance(payload, dict):
            payload["_capture_truncated"] = True
        else:
            payload = {"body": payload, "_capture_truncated": True}

    return payload, truncated


def _extract_response_metadata(payload: Any) -> tuple[Any, Any, Any, Any]:
    model = None
    usage = None

    if isinstance(payload, dict):
        model = payload.get("model")
        usage = payload.get("usage")
        for event in payload.get("events", []):
            if isinstance(event, dict):
                model = event.get("model") or model
                usage = event.get("usage") or usage

    if not isinstance(usage, dict):
        return model, None, None, None

    return (
        model,
        usage.get("prompt_tokens"),
        usage.get("completion_tokens"),
        usage.get("total_tokens"),
    )


def _forward_headers(headers: dict[str, str]) -> dict[str, str]:
    blocked = {
        "authorization",
        "connection",
        "content-length",
        "host",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailers",
        "transfer-encoding",
        "upgrade",
    }
    forwarded = {key: value for key, value in headers.items() if key.lower() not in blocked}
    if UPSTREAM_API_KEY:
        forwarded["Authorization"] = f"Bearer {UPSTREAM_API_KEY}"
    return forwarded


def _forward_response_headers(headers: httpx.Headers) -> dict[str, str]:
    blocked = {
        "connection",
        "content-encoding",
        "content-length",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailers",
        "transfer-encoding",
        "upgrade",
    }
    return {key: value for key, value in headers.items() if key.lower() not in blocked}


def validate_gateway_token(token: str, signing_key: str) -> str:
    try:
        version, participant_id, signature = token.split(".", 2)
    except ValueError as exc:
        raise ValueError("Invalid gateway token format") from exc

    if version != "v1" or len(participant_id) != 64:
        raise ValueError("Invalid gateway token payload")

    signed_value = f"{version}.{participant_id}"
    expected = base64.urlsafe_b64encode(
        hmac.new(signing_key.encode(), signed_value.encode(), hashlib.sha256).digest()
    ).decode().rstrip("=")

    if not hmac.compare_digest(signature, expected):
        raise ValueError("Invalid gateway token signature")

    return participant_id


def _extract_bearer_token(request: Request) -> str:
    authorization = request.headers.get("authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise ValueError("Missing bearer token")
    return token.strip()


async def _insert_interaction(event: dict[str, Any]) -> None:
    if pool is None:
        raise RuntimeError("Database pool is not initialized")

    async with pool.acquire() as conn:
        await conn.execute(
            INSERT_INTERACTION_SQL,
            event["interaction_id"],
            event["participant_id"],
            event["deployment_id"],
            event["consent_version"],
            event["client_name"],
            event["request_started_at"],
            event["request_completed_at"],
            event["status"],
            event["upstream_status"],
            event["method"],
            event["path"],
            event["query"],
            event["model_requested"],
            event["model_returned"],
            event["duration_ms"],
            event["prompt_tokens"],
            event["completion_tokens"],
            event["total_tokens"],
            json.dumps(event["request_payload"]),
            json.dumps(event["response_payload"]),
            event["request_truncated"],
            event["response_truncated"],
            event["capture_content"],
            event["error"],
        )


@app.api_route("/v1/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])
async def proxy(path: str, request: Request) -> Response:
    started_perf = time.perf_counter()
    started_at = datetime.now(timezone.utc)

    try:
        participant_id = validate_gateway_token(_extract_bearer_token(request), GATEWAY_SIGNING_KEY)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=401)

    body = await request.body()
    request_payload, request_truncated = _capture_payload(
        body,
        request.headers.get("content-type", ""),
        MAX_CAPTURE_BYTES,
        CAPTURE_CONTENT,
    )

    upstream_url = f"{UPSTREAM_BASE_URL}/{path}"
    if request.url.query:
        upstream_url = f"{upstream_url}?{request.url.query}"

    status = "completed"
    upstream_status = None
    error = None

    try:
        upstream_response = await client.request(
            request.method,
            upstream_url,
            content=body,
            headers=_forward_headers(dict(request.headers)),
        )
        response_body = upstream_response.content
        upstream_status = upstream_response.status_code
        status_code = upstream_response.status_code
        media_type = upstream_response.headers.get("content-type", "application/json")
        response_payload, response_truncated = _capture_payload(
            response_body,
            media_type,
            MAX_CAPTURE_BYTES,
            CAPTURE_CONTENT,
        )
        response_headers = _forward_response_headers(upstream_response.headers)
        if upstream_status >= 400:
            status = "upstream_error"
    except httpx.HTTPError as exc:
        status = "gateway_error"
        status_code = 502
        response_body = json.dumps({"error": str(exc)}).encode("utf-8")
        response_payload = {"error": str(exc)}
        response_truncated = False
        response_headers = {"content-type": "application/json"}
        media_type = "application/json"
        error = str(exc)

    completed_at = datetime.now(timezone.utc)
    duration_ms = round((time.perf_counter() - started_perf) * 1000, 2)
    model_returned, prompt_tokens, completion_tokens, total_tokens = _extract_response_metadata(
        response_payload
    )
    event = {
        "interaction_id": uuid.uuid4(),
        "participant_id": participant_id,
        "deployment_id": DEPLOYMENT_ID,
        "consent_version": CONSENT_VERSION,
        "client_name": request.headers.get("x-llm-client"),
        "request_started_at": started_at,
        "request_completed_at": completed_at,
        "status": status,
        "upstream_status": upstream_status,
        "method": request.method,
        "path": f"/v1/{path}",
        "query": request.url.query,
        "model_requested": request_payload.get("model") if isinstance(request_payload, dict) else None,
        "model_returned": model_returned,
        "duration_ms": duration_ms,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "request_payload": request_payload,
        "response_payload": response_payload,
        "request_truncated": request_truncated,
        "response_truncated": response_truncated,
        "capture_content": CAPTURE_CONTENT,
        "error": error,
    }

    try:
        await _insert_interaction(event)
    except Exception as exc:
        if LOGGING_FAILURE_POLICY == "deny":
            return JSONResponse({"error": "logging_failed", "detail": str(exc)}, status_code=500)

    return Response(
        content=response_body,
        status_code=status_code,
        headers=response_headers,
        media_type=media_type,
    )
