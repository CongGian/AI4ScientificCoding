# LLM Logging Proxy

This package provides a small FastAPI proxy that sits in front of the shared LLM endpoint, forwards OpenAI-compatible requests, and appends JSONL logs for later research analysis.

Each user container writes to its own file under `LLM_LOG_DIR`, which can be mounted from a shared Docker volume so logs remain available after containers are removed.
