#!/usr/bin/env python3
"""Compute the database pseudonym for a JupyterHub username."""

import hashlib
import hmac
import os
import sys

if len(sys.argv) != 2:
    raise SystemExit(f"Usage: {sys.argv[0]} <github-username>")

key = os.environ.get("LLM_PSEUDONYMIZATION_KEY")
if not key:
    raise SystemExit("LLM_PSEUDONYMIZATION_KEY is not set")

username = sys.argv[1].strip().lower()
print(hmac.new(key.encode(), username.encode(), hashlib.sha256).hexdigest())
