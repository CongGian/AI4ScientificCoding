from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, Request, Response

UPSTREAM_BASE_URL = os.environ.get(
	"LLM_UPSTREAM_BASE_URL",
	os.environ.get("OPENAI_BASE_URL", "https://llm.jetstream-cloud.org/v1"),
).rstrip("/")
DEFAULT_LOG_DIR = Path(os.environ.get("HOME", "/tmp")) / ".local/share/llm-proxy/logs"
LOG_DIR = Path(os.environ.get("LLM_LOG_DIR", str(DEFAULT_LOG_DIR)))
LOG_DIR.mkdir(parents=True, exist_ok=True)
USER_NAME = os.environ.get("JUPYTERHUB_USER") or os.environ.get("USER") or "unknown"
LOG_FILE = LOG_DIR / f"{USER_NAME}.jsonl"
CAPTURE_CONTENT = os.environ.get("LLM_CAPTURE_CONTENT", "true").lower() not in {
	"0",
	"false",
	"no",
}
MAX_CAPTURE_BYTES = int(os.environ.get("LLM_MAX_CAPTURE_BYTES", "10485760"))

app = FastAPI(title="AI4ScientificCoding LLM Logging Proxy")
client = httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=30.0))
log_lock = threading.Lock()


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


def _forward_response_headers(headers: httpx.Headers) -> dict[str, str]:
	hop_by_hop = {
		"connection",
		"keep-alive",
		"proxy-authenticate",
		"proxy-authorization",
		"te",
		"trailers",
		"transfer-encoding",
		"upgrade",
		"content-length",
		"content-encoding",
	}
	return {
		key: value
		for key, value in headers.items()
		if key.lower() not in hop_by_hop
	}


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


def _append_log(event: dict[str, Any]) -> None:
	line = json.dumps(event, ensure_ascii=True, sort_keys=True)
	with log_lock:
		with LOG_FILE.open("a", encoding="utf-8") as handle:
			handle.write(line + "\n")


@app.on_event("shutdown")
async def _shutdown_client() -> None:
	await client.aclose()


@app.get("/")
async def healthcheck() -> dict[str, str]:
	return {"status": "ok", "upstream": UPSTREAM_BASE_URL, "user": USER_NAME}


@app.api_route("/v1/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])
async def proxy(path: str, request: Request) -> Response:
	started_at = time.perf_counter()
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

	headers = dict(request.headers)
	headers.pop("host", None)
	headers.pop("content-length", None)

	try:
		upstream_response = await client.request(
			request.method,
			upstream_url,
			content=body,
			headers=headers,
		)
		response_body = upstream_response.content
		status_code = upstream_response.status_code
		media_type = upstream_response.headers.get("content-type", "application/json")
		response_payload, response_truncated = _capture_payload(
			response_body,
			media_type,
			MAX_CAPTURE_BYTES,
			CAPTURE_CONTENT,
		)
		response_headers = _forward_response_headers(upstream_response.headers)
	except httpx.HTTPError as exc:
		status_code = 502
		response_body = json.dumps({"error": str(exc)}).encode("utf-8")
		response_payload = {"error": str(exc)}
		response_truncated = False
		response_headers = {"content-type": "application/json"}
		media_type = "application/json"

	elapsed_ms = round((time.perf_counter() - started_at) * 1000, 2)
	model_returned, prompt_tokens, completion_tokens, total_tokens = _extract_response_metadata(
		response_payload
	)
	log_event = {
		"timestamp": datetime.now(timezone.utc).isoformat(),
		"user": USER_NAME,
		"method": request.method,
		"path": f"/v1/{path}",
		"query": request.url.query,
		"status_code": status_code,
		"duration_ms": elapsed_ms,
		"model_requested": request_payload.get("model") if isinstance(request_payload, dict) else None,
		"model_returned": model_returned,
		"prompt_tokens": prompt_tokens,
		"completion_tokens": completion_tokens,
		"total_tokens": total_tokens,
		"request_truncated": request_truncated,
		"response_truncated": response_truncated,
		"request": request_payload,
		"response": response_payload,
	}
	_append_log(log_event)

	return Response(
		content=response_body,
		status_code=status_code,
		headers=response_headers,
		media_type=media_type,
	)
