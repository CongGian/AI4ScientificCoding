# LLM Gateway

FastAPI gateway for OpenAI-compatible LLM traffic. It validates signed
pseudonymous participant tokens, forwards requests to the Jetstream LLM endpoint,
and writes interaction metadata/content to PostgreSQL.

The gateway is intended to run centrally in the JupyterHub namespace. Notebook
containers should receive only a signed participant token, not the upstream LLM
credential or database credentials.
