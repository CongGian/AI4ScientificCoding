#  JupyterHub Deployment 

> Multi-user JupyterHub with GitHub OAuth authentication, GPU-accelerated PyTorch containers, and isolated environments per user. Deployed on Jetstream2 

---

## 📌 Quick Access

| | |
|---|---|
| **URL** | http://149.165.172.98:8000 |
| **URL (SSL)** | https://srp-jupyterhub.nairr240257.projects.jetstream-cloud.org/ |
| **Login** | GitHub OAuth (NCSU-NNDL-Spring26 org) |
| **GPU** | NVIDIA GRID A100X-10C (10GB, CUDA 12.2) |
| **Notebook** | PyTorch + JupyterLab + Jupyter AI (Python 3.12) |

---

## Architecture
Student Browser
│
▼
JupyterHub (port 8000)  ←── GitHub OAuth Authentication
│
▼
DockerSpawner
│
▼
Personal PyTorch Container (per user)
│
▼
NVIDIA GRID A100X-10C GPU (CUDA 12.2)

Each student gets a **fully isolated** JupyterLab environment with GPU access.

---

## ⚙️ Initial Setup

### Prerequisites
- Docker installed on host VM
- GitHub OAuth App credentials
- VM with NVIDIA GPU + CUDA drivers

### Step 0: Set environment variables
Create a `.env` file at repo root and set environment variables

```
GITHUB_CLIENT_ID=...
GITHUB_CLIENT_SECRET=...
OAUTH_CALLBACK_URL=...
DOCKER_NOTEBOOK_IMAGE=ai4scientificcoding-notebook:latest
# Optional shared Jupyter AI provider key, if all users should use the same key:
# OPENAI_API_KEY=...
```

### Step 1: Create Docker Network
```bash
docker network create jupyterhub-network
```

### Step 2: Build the Notebook Image with Jupyter AI
```bash
docker build -f jupyterhub/Dockerfile.notebook -t ai4scientificcoding-notebook:latest .
```

### Step 3: Build Complete JupyterHub Image
```bash
docker build -f jupyterhub/Dockerfile -t jupyterhub-complete:latest .
```

### Step 4: Create Config File
```bash
mkdir -p ~/jupyterhub-config
cp jupyterhub/jupyterhub_config.py ~/jupyterhub-config/jupyterhub_config.py
# Edit the file and add your Client ID and Secret
```

### Step 5: Run JupyterHub
```bash
docker run -d \
  --name jupyterhub \
  --network jupyterhub-network \
  -p 8000:8000 \
  -v ~/jupyterhub-config:/etc/jupyterhub \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v jupyterhub-data:/data \
  jupyterhub-complete:latest \
  jupyterhub -f /etc/jupyterhub/jupyterhub_config.py
```

### Step 6: Verify
```bash
docker ps | grep jupyterhub
# Visit http://149.165.172.98:8000
```

---

## 🔐 GitHub OAuth Setup

### Create OAuth App
1. Go to: https://github.com/organizations/NCSU-NNDL-Spring26/settings/applications
2. Click **New OAuth App**
3. Fill in the following fields:

| Field | Value |
|-------|-------|
| Application name | Jetstream Classroom |
| Homepage URL | http://149.165.172.98:8000 |
| Authorization callback URL | http://149.165.172.98:8000/hub/oauth_callback |

4. Click **Register application**
5. Click **Generate a new client secret**
6. Save the **Client ID** and **Client Secret** securely

### Add Credentials to Config
Open `~/jupyterhub-config/jupyterhub_config.py` and update:
```python
c.GitHubOAuthenticator.client_id = "YOUR_CLIENT_ID"
c.GitHubOAuthenticator.client_secret = "YOUR_CLIENT_SECRET"
```

> ⚠️ **Never commit your Client Secret to GitHub!**

---

## 👥 Managing Users

### Adding New Users
Open `~/jupyterhub-config/jupyterhub_config.py` and add the GitHub username:

```python
c.Authenticator.allowed_users = [
    "lobaton",
    "darrendbutler",
    "qsamson",
    "new-github-username",   # ← Add new user here
]
```

### Apply Changes
```bash
docker restart jupyterhub
```

## 💾 Persistent Storage and LLM Logging

The notebook config now mounts a host-path directory into each user container for persistent per-user workspaces:

- `/media/volume/jupyterhub/users/{username}` at `/home/jovyan/work` for per-user notebooks and files
- `jupyterhub-llm-logs` at `/var/log/llm-proxy` for JSONL logs of prompts and model responses

Before starting JupyterHub, create the base directory on the VM and mount it from the Jetstream volume, for example:

```bash
sudo mkdir -p /media/volume/jupyterhub/users
sudo chown -R root:root /media/volume/jupyterhub
```

If you prefer Docker-managed named volumes instead, set `JUPYTERHUB_USER_STORAGE_ROOT` to a Docker volume root pattern before starting the Hub.

### Removing a User
Simply remove their username from the list above and restart.

---

## 🔧 Common Commands

```bash
# Check JupyterHub status
docker ps | grep jupyterhub

# View logs
docker logs jupyterhub --tail 50

# Restart JupyterHub
docker restart jupyterhub

# Stop JupyterHub
docker stop jupyterhub

# List active user containers
docker ps | grep jupyter-
```

---

## ✅ Verify GPU Access

Inside any user's JupyterLab terminal:
```python
python -c "import torch; print(torch.cuda.is_available()); print(torch.cuda.get_device_name(0))"
# Expected: True / GRID A100X-10C

nvidia-smi
# Expected: GRID A100X-10C, 10240MiB
```

---

## ✅ Verify Jupyter AI Access

Inside any user JupyterLab terminal:
```bash
python -c "import jupyter_ai; print(jupyter_ai.__version__)"
# Expected: prints the installed Jupyter AI version
```

---

## 📁 Files

| File | Purpose |
|------|---------|
| `README.md` | This documentation |
| `Dockerfile` | Complete JupyterHub image with all dependencies |
| `Dockerfile.notebook` | User notebook image with Jupyter AI and the custom persona package |
| `notebook-requirements.txt` | Python packages installed into spawned user notebook containers |
| `jupyterhub_config.py` | Configuration template (no secrets) |

---

## ⚠️ Security Notes

- Never commit `client_secret` to GitHub
- HTTPS is strongly recommended for production (HTTP warning shown on login)
- Only whitelisted GitHub users can access the Hub
- Each user's container is fully isolated

---

## 👨‍💻 Maintainers

| Name | GitHub | Role |
|------|--------|------|
| Samson Quaye | @qsamson | Lead Developer |
| Ren Butler | @darrendbutler | Infrastructure |
| Prof. Edgar Lobaton | @lobaton | Principal Investigator |

---

*SHI-NAIRR SRP 2026 — NC State University, ECE Department*
