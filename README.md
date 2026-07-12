# AI4ScientificCoding

AI4ScientificCoding provides a multi-user JupyterHub deployment for scientific coding classes. Users authenticate with GitHub, land in JupyterLab, and receive an isolated GPU-ready notebook container with PyTorch, Jupyter AI, and VS Code plus Cline exposed through the JupyterLab launcher.

## What This Deploys

- JupyterHub on port 8000
- GitHub OAuth authentication through `oauthenticator`
- DockerSpawner-backed per-user notebook containers
- CUDA 12 PyTorch notebook image
- JupyterLab as the default user interface
- Jupyter AI plus the local course persona package in `jupyter-ai/`
- code-server exposed in JupyterLab as `VS Code + Cline`
- Cline extension and CLI configured from `.env`
- A per-user persistent work volume plus a shared JSONL log volume for LLM requests and responses
- A local FastAPI LLM proxy inside each spawned user container so Jupyter AI, Cline, and Marimo can share the same logged upstream path
- Optional GPU access through the NVIDIA Docker runtime

## Repository Layout

| Path | Purpose |
|------|---------|
| `jupyterhub/Dockerfile` | Builds the Hub image with JupyterHub, OAuth, and DockerSpawner dependencies |
| `jupyterhub/Dockerfile.notebook` | Builds the spawned user notebook image with PyTorch, JupyterLab, Jupyter AI, code-server, and Cline |
| `jupyterhub/jupyterhub_config.py` | Runtime Hub config for GitHub OAuth, DockerSpawner, JupyterLab, Cline, Jupyter AI, and GPU access |
| `jupyterhub/requirements.txt` | Python packages installed in the Hub image |
| `jupyterhub/notebook-requirements.txt` | Python packages installed in spawned notebook containers |
| `jupyterhub/jupyter_server_config.py` | Registers the JupyterLab launcher entry for VS Code plus Cline |
| `jupyterhub/start-jupyterhub.sh` | Helper script for starting the Hub container |
| `cline-vscode-integration/start-code-server.sh` | Starts code-server and writes per-user Cline settings from environment variables |
| `jupyter-ai/` | Local Jupyter AI persona/package installed into notebook containers |

## Prerequisites

Install these on the host VM that will run JupyterHub:

- Docker Engine
- Git
- NVIDIA GPU drivers, if GPU notebooks are required
- NVIDIA Container Toolkit, if GPU notebooks are required
- A GitHub OAuth App
- A DNS name and HTTPS reverse proxy for production deployments

For GPU support, verify the host can run NVIDIA containers:

```bash
docker run --rm --gpus all nvidia/cuda:12.2.0-base-ubuntu22.04 nvidia-smi
```

## Development Environment

Clone the repository and enter it:

```bash
git clone <repo-url>
cd AI4ScientificCoding
```

Create an optional local Python environment for linting and editor support:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r jupyterhub/requirements.txt
pip install -r jupyterhub/notebook-requirements.txt
```

Run local syntax checks before building images:

```bash
python3 -m py_compile jupyterhub/jupyterhub_config.py jupyterhub/jupyter_server_config.py
bash -n jupyterhub/start-jupyterhub.sh
bash -n cline-vscode-integration/start-code-server.sh
```

## GitHub OAuth Setup

Create a GitHub OAuth App in the GitHub organization or account that will control access.

Use these values, replacing the host with the public Hub URL:

| Field | Value |
|-------|-------|
| Homepage URL | `https://<hub-domain>/` |
| Authorization callback URL | `https://<hub-domain>/hub/oauth_callback` |

For local or HTTP testing, use the same pattern with `http://<host>:8000/hub/oauth_callback`.

## Environment File

Create `.env` at the repository root. This file is loaded into the Hub container by `jupyterhub/start-jupyterhub.sh`. The file is intentionally ignored by git and must not be committed.

Required for GitHub OAuth:

```bash
GITHUB_CLIENT_ID=...
GITHUB_CLIENT_SECRET=...
OAUTH_CALLBACK_URL=https://<hub-domain>/hub/oauth_callback
```

Recommended deployment settings:

```bash
# GitHub organization allowed to log in.
GITHUB_ALLOWED_ORG=NCSU-NNDL-Spring26

# Image spawned for each user. This must match the notebook image tag built below.
DOCKER_NOTEBOOK_IMAGE=ai4scientificcoding-notebook:latest
```

Required for Cline to authenticate to the shared model provider:

```bash
CLINE_API_PROVIDER=openai-compatible
CLINE_API_KEY=...
CLINE_BASE_URL=https://llm.jetstream-cloud.org/v1
CLINE_MODEL=Kimi-K2.6
CLINE_VERSION=3.88.1

# Optional overrides for storage and logging volumes.
# If you move Docker's data-root to the Jetstream attached disk, these named volumes will live on that disk too.
# JUPYTERHUB_USER_STORAGE_VOLUME_PREFIX=jupyterhub-user
# JUPYTERHUB_LLM_LOG_VOLUME=jupyterhub-llm-logs
```

Optional Jupyter AI provider keys:

```bash
# Add these only if it is acceptable for every notebook user to inspect them.
# The Hub passes these into spawned notebook containers when set.
# OPENAI_API_KEY=...
# ANTHROPIC_API_KEY=...
# GOOGLE_API_KEY=...
# JUPYTER_AI_DEFAULT_MODEL=...
```

Security notes for `.env`:

- `GITHUB_CLIENT_SECRET` and `CLINE_API_KEY` are secrets.
- Jupyter AI provider keys are also secrets.
- Any variable passed into user notebook containers can be read by users inside those containers.
- Do not add shared Jupyter AI provider keys unless sharing them with all Hub users is intentional.
- If a secret is pasted into chat, committed, logged, or otherwise exposed, rotate it in the provider dashboard.

## Build Images

All Docker builds should use the repository root as the build context.

Build the user notebook image with JupyterLab, PyTorch, Jupyter AI, code-server, and Cline:

```bash
docker build -f jupyterhub/Dockerfile.notebook -t ai4scientificcoding-notebook:latest .
```

Build the JupyterHub image:

```bash
docker build -f jupyterhub/Dockerfile -t jupyterhub-complete:latest .
```

## Deploy the Hub

Start JupyterHub from the repository root:

```bash
./jupyterhub/start-jupyterhub.sh
```

The script will:

- Create `jupyterhub-network` if it does not exist
- Load environment variables from `.env`
- Mount `jupyterhub/` into `/etc/jupyterhub`
- Mount `/var/run/docker.sock` so DockerSpawner can create user containers
- Mount the persistent `jupyterhub-data` Docker volume
- Start the Hub image as a container named `jupyterhub`

The script refuses to replace an existing Hub container. To redeploy:

```bash
docker rm -f jupyterhub
./jupyterhub/start-jupyterhub.sh
```

You can override script defaults when needed:

```bash
HUB_PORT=8080 HUB_NAME=jupyterhub-dev ./jupyterhub/start-jupyterhub.sh
```

Supported script overrides are `ENV_FILE`, `HUB_IMAGE`, `HUB_NAME`, `HUB_NETWORK`, and `HUB_PORT`.

## Verify Deployment

Check the Hub container:

```bash
docker ps --filter name=jupyterhub
```

Watch logs:

```bash
docker logs -f jupyterhub
```

Visit the Hub URL and sign in with a GitHub account in the allowed organization.

Inside a spawned user JupyterLab terminal, verify GPU access:

```bash
python -c "import torch; print(torch.cuda.is_available()); print(torch.cuda.get_device_name(0) if torch.cuda.is_available() else None)"
nvidia-smi
```

Verify Jupyter AI is installed:

```bash
python -c "import jupyter_ai; print(jupyter_ai.__version__)"
```

Verify VS Code plus Cline:

1. Open JupyterLab.
2. In the launcher, click `VS Code + Cline`.
3. Confirm code-server opens in the browser.
4. Open the Cline extension sidebar in code-server.
5. In a JupyterLab or code-server terminal, run:

```bash
cline --help
```

If `CLINE_API_KEY` is not set in `.env`, code-server can still launch, but Cline provider authentication will not be useful until a key is provided.

## Rebuild and Roll Out Changes

When `Dockerfile.notebook`, `notebook-requirements.txt`, `jupyter-ai/`, `jupyter_server_config.py`, or the Cline startup script changes, rebuild the notebook image:

```bash
docker build -f jupyterhub/Dockerfile.notebook -t ai4scientificcoding-notebook:latest .
```

Existing user containers keep using the old image. Remove old user containers so DockerSpawner creates fresh ones at next login:

```bash
docker ps -a --filter name=jupyter- --format "{{.ID}} {{.Names}}"
docker rm -f <container-id>
```

When `jupyterhub/Dockerfile`, `jupyterhub/requirements.txt`, or Hub-level dependencies change, rebuild and restart the Hub image:

```bash
docker build -f jupyterhub/Dockerfile -t jupyterhub-complete:latest .
docker rm -f jupyterhub
./jupyterhub/start-jupyterhub.sh
```

When only `jupyterhub/jupyterhub_config.py` changes, restart the Hub container:

```bash
docker restart jupyterhub
```

When only `.env` changes, restart the Hub container and recreate any user containers that need updated environment variables:

```bash
docker restart jupyterhub
docker rm -f <user-container-id>
```

## Operational Notes

- JupyterHub itself does not contain user tools. User tools belong in `jupyterhub/Dockerfile.notebook` and `jupyterhub/notebook-requirements.txt`.
- `jupyterhub/jupyterhub_config.py` must point `c.DockerSpawner.image` at the notebook image that contains Jupyter AI, code-server, and Cline.
- The Hub container needs `/var/run/docker.sock` mounted so DockerSpawner can create user containers.
- Production deployments should run behind HTTPS. GitHub OAuth callbacks should use the final HTTPS URL.
- Shared API keys in `.env` are visible to spawned user containers when passed through by the Hub config. Use shared keys only when that is intended for the course.

## Common Troubleshooting

| Symptom | Check |
|---------|-------|
| GitHub login fails | Verify `OAUTH_CALLBACK_URL` exactly matches the GitHub OAuth App callback URL |
| User is denied after GitHub login | Verify the GitHub account belongs to `GITHUB_ALLOWED_ORG` |
| Jupyter AI is missing | Rebuild `ai4scientificcoding-notebook:latest` and remove the old user container |
| VS Code plus Cline launcher is missing | Verify `jupyter-server-proxy` is installed and `jupyterhub/jupyter_server_config.py` was copied into the notebook image |
| Cline cannot reach the model provider | Check `CLINE_API_KEY`, `CLINE_BASE_URL`, and `CLINE_MODEL` in `.env` |
| Environment variable changes do not appear in notebooks | Restart the Hub and recreate the affected user containers |
| GPU is unavailable | Verify NVIDIA Container Toolkit and `c.DockerSpawner.extra_host_config = {"runtime": "nvidia"}` |
