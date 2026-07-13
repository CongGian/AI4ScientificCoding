FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY llm-proxy/pyproject.toml llm-proxy/README.md /app/
COPY llm-proxy/llm_proxy /app/llm_proxy

RUN pip install --no-cache-dir .

USER 65532:65532

EXPOSE 8010

CMD ["uvicorn", "llm_proxy.app:app", "--host", "0.0.0.0", "--port", "8010", "--proxy-headers"]
