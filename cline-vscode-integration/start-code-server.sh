#!/bin/bash
# Prepare Cline for a JupyterHub single-user container. DockerSpawner runs this
# before the Jupyter single-user server starts; jupyter-server-proxy launches
# code-server when the user clicks the VS Code + Cline launcher.
set -euo pipefail

# Jupyter Docker Stacks run notebook containers as the jovyan user. Set HOME and
# XDG_DATA_HOME explicitly so code-server and Cline write settings in the user
# workspace instead of a root-owned or unset location.
export HOME=/home/jovyan
export XDG_DATA_HOME=/home/jovyan/.local/share

# Cline provider defaults. JupyterHub passes CLINE_API_KEY from .env when set.
# Keep the key out of tracked files; leave it empty here if not provided.
export CLINE_API_PROVIDER=${CLINE_API_PROVIDER:-openai-compatible}
export OPENAI_BASE_URL=${OPENAI_BASE_URL:-https://llm.jetstream-cloud.org/v1}
export OPENAI_API_BASE=${OPENAI_API_BASE:-${OPENAI_BASE_URL}}
export OPENAI_API_KEY=${OPENAI_API_KEY:-${CLINE_API_KEY:-}}
export CLINE_API_KEY=${CLINE_API_KEY:-${OPENAI_API_KEY}}
export CLINE_MODEL=${CLINE_MODEL:-Kimi-K2.6}
export CLINE_BASE_URL=${CLINE_BASE_URL:-${OPENAI_BASE_URL}}
export CLINE_VERSION=${CLINE_VERSION:-3.88.1}
export MARIMO_BASE_URL=${MARIMO_BASE_URL:-${OPENAI_BASE_URL}}
export MARIMO_API_KEY=${MARIMO_API_KEY:-${OPENAI_API_KEY}}

# Ensure the per-user settings directories exist before writing config files.
mkdir -p /home/jovyan/.local/share/code-server/User
mkdir -p /home/jovyan/.cline/data/settings

# Configure code-server defaults for classroom use: disable workspace trust
# prompts, enable autosave, and use bash as the integrated terminal shell.
cat > /home/jovyan/.local/share/code-server/User/settings.json << SETTINGS
{
  "security.workspace.trust.enabled": false,
  "files.autoSave": "onFocusChange",
  "terminal.integrated.defaultProfile.linux": "bash"
}
SETTINGS

# Write Cline extension state as JSON. Python handles quoting safely, which is
# less fragile than assembling nested JSON with shell string interpolation.
python3 - << PY
import json
import os
from pathlib import Path

provider = os.environ["CLINE_API_PROVIDER"]
api_key = os.environ["CLINE_API_KEY"]
model = os.environ["CLINE_MODEL"]
base_url = os.environ["CLINE_BASE_URL"]
version = os.environ["CLINE_VERSION"]

settings_dir = Path("/home/jovyan/.cline/data/settings")
settings_dir.mkdir(parents=True, exist_ok=True)

(settings_dir / "providers.json").write_text(json.dumps({
    "version": 1,
    "lastUsedProvider": provider,
    "providers": {
        provider: {
            "settings": {
                "provider": provider,
                "apiKey": api_key,
                "model": model,
                "baseUrl": base_url,
            }
        }
    },
}))

Path("/home/jovyan/.cline/data/globalState.json").write_text(json.dumps({
    "welcomeViewCompleted": True,
    "clineVersion": version,
    "planModeApiProvider": provider,
    "actModeApiProvider": provider,
    "openAiBaseUrl": base_url,
    "planModeOpenAiModelId": model,
    "actModeOpenAiModelId": model,
    "azureApiVersion": "",
}))
PY

# Authenticate the Cline CLI when it is available. Do not fail container startup
# if the auth command changes or the provider is temporarily unreachable.
if command -v cline >/dev/null 2>&1; then
  cline auth -p "${CLINE_API_PROVIDER}" -k "${CLINE_API_KEY}" -m "${CLINE_MODEL}" -b "${CLINE_BASE_URL}" || true
fi

# Clone assignment repo in background
(
  mkdir -p /home/jovyan/assignments
  if [ ! -d "/home/jovyan/assignments/hw01-foundations" ]; then
    git clone https://qsamson:${GITHUB_TOKEN}@github.com/NCSU-NNDL-Spring26/hw01-foundations /home/jovyan/assignments/hw01-foundations
  else
    git -C /home/jovyan/assignments/hw01-foundations pull
  fi
) &

# Configure Marimo AI settings
mkdir -p /home/jovyan/.config/marimo
cat > /home/jovyan/.config/marimo/marimo.toml << MARIMO
[ai]
enabled = true
inline_tooltip = false
mode = "agent"
rules = ""
[ai.custom_providers.jetstream]
api_key = "${MARIMO_API_KEY}"
base_url = "${MARIMO_BASE_URL}"
[ai.models]
autocomplete_model = "jetstream/gpt-oss-120b"
chat_model = "jetstream/gpt-oss-120b"
custom_models = ["jetstream/gpt-oss-120b", "jetstream/Llama-4-Scout"]
displayed_models = ["jetstream/gpt-oss-120b", "jetstream/Llama-4-Scout"]
[completion]
activate_on_typing = true
copilot = "custom"
MARIMO

# Configure Cline CLI defaults (fast mode, no verbose thinking)
mkdir -p /home/jovyan/.config/cline
cat > /home/jovyan/.config/cline/config.json << 'CLINE_CONFIG'
{
  "thinking": "none",
  "autoApprove": true,
  "compaction": "off"
}
CLINE_CONFIG

# Create default .clinerules for concise responses
cat > /home/jovyan/.clinerules << 'RULES'
# Classroom Assistant Rules
- Be concise and direct
- Do not explore files unless specifically asked
- Do not run verification commands after creating files unless asked
- Do not provide lengthy summaries after completing tasks
- Answer the question asked, nothing more
- Do not read existing files to check conventions unless asked
RULES

# Apply Cline teaching assistant persona
python3 -c "
from ai4scientificcoding_cline_tutor.persona import GptOssClineTutorPersona
GptOssClineTutorPersona().apply()
"
