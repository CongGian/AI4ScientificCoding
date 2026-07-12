# Jetstream Research Logging and Persistent User Storage

## Architecture

All OpenAI-compatible traffic from Jupyter AI, Cline, and Marimo goes to one
`llm-gateway` container. The gateway validates a signed per-user token, replaces
it with the upstream provider credential, streams the response back to the
client, and stores a pseudonymous interaction record in PostgreSQL.

Notebook containers never receive the upstream API key, database credentials,
or a research-data mount. Each notebook receives only its own signed gateway
token and its own private workspace bind-mounted from the Jetstream volume.

```text
Jupyter AI / Cline / Marimo
           |
           | signed pseudonymous user token
           v
      llm-gateway  ------> upstream LLM
           |
           v
  PostgreSQL on Jetstream volume
```

## 1. Verify the attached Jetstream volume

Do this before creating any directory or building an image. On the current VM,
the attached device is `/dev/sdb` and its real mount point is
`/media/volume/SRP-JupyterHub`. `/media/volume` by itself is on the root disk.

```bash
lsblk -o NAME,SIZE,FSTYPE,UUID,MOUNTPOINTS
findmnt -T /media/volume/SRP-JupyterHub
df -h / /media/volume/SRP-JupyterHub
```

The `findmnt` source must be the attached block device, not `/dev/sda1`.
Persist the mount across reboots if it is not already in `/etc/fstab`:

```bash
sudo mkdir -p /media/volume/SRP-JupyterHub
sudo blkid /dev/sdb
```

Add an entry using the UUID printed by `blkid`:

```text
UUID=<volume-uuid> /media/volume/SRP-JupyterHub ext4 defaults,nofail 0 2
```

Then validate it without rebooting:

```bash
sudo mount -a
findmnt -T /media/volume/SRP-JupyterHub
```

## 2. Move both Docker and containerd off the root disk

Checking only Docker's `DockerRootDir` is insufficient on this VM. Docker uses
the system containerd daemon, whose default root is `/var/lib/containerd`. A test
notebook build increased `/dev/sda1` usage by about 5 GB even though Docker
reported its data root on `/dev/sdb`.

Check both locations:

```bash
DOCKER_ROOT=$(docker info --format '{{.DockerRootDir}}')
CONTAINERD_ROOT=$(containerd config dump | sed -n "s/^root = ['\"]\(.*\)['\"]$/\1/p" | head -1)

printf 'Docker:     %s\ncontainerd: %s\n' "$DOCKER_ROOT" "$CONTAINERD_ROOT"
findmnt -T "$DOCKER_ROOT"
findmnt -T "$CONTAINERD_ROOT"
df -h / "$DOCKER_ROOT" "$CONTAINERD_ROOT"
```

Both paths must resolve to `JETSTREAM_VOLUME_MOUNT` before rebuilding the large
notebook image. On the inspected VM, Docker is correctly configured at
`/media/volume/SRP-JupyterHub/docker`, but containerd is still using
`/var/lib/containerd` on the root disk.

Moving containerd requires a maintenance window because all containers stop.
First ensure the Jetstream mount is persistent in `/etc/fstab`, then:

```bash
export JETSTREAM_VOLUME_MOUNT=/media/volume/SRP-JupyterHub
: "${JETSTREAM_VOLUME_MOUNT:?JETSTREAM_VOLUME_MOUNT must be set}"
[ "$(findmnt -n -o TARGET -T "$JETSTREAM_VOLUME_MOUNT")" = "$JETSTREAM_VOLUME_MOUNT" ] || { echo "Not a mount: $JETSTREAM_VOLUME_MOUNT"; exit 1; }
[ "$(findmnt -n -o SOURCE -T "$JETSTREAM_VOLUME_MOUNT")" != "/dev/sda1" ] || { echo "Refusing root disk"; exit 1; }

sudo systemctl stop docker.service docker.socket containerd.service
sudo mkdir -p "$JETSTREAM_VOLUME_MOUNT/containerd"
sudo rsync -aHAX --numeric-ids   /var/lib/containerd/ "$JETSTREAM_VOLUME_MOUNT/containerd/"

sudo mkdir -p /etc/containerd
sudo cp -a /etc/containerd/config.toml   /etc/containerd/config.toml.pre-jetstream 2>/dev/null || true
sudo tee /etc/containerd/config.toml >/dev/null <<EOF
version = 3
root = "$JETSTREAM_VOLUME_MOUNT/containerd"
state = "/run/containerd"
EOF

sudo mkdir -p /etc/systemd/system/containerd.service.d
sudo tee /etc/systemd/system/containerd.service.d/jetstream-mount.conf >/dev/null <<EOF
[Unit]
RequiresMountsFor=$JETSTREAM_VOLUME_MOUNT
After=local-fs.target
EOF

sudo systemctl daemon-reload
sudo systemctl start containerd.service docker.service
```

Validate before deleting anything:

```bash
containerd config dump | sed -n '1,5p'
docker info --format 'DockerRootDir={{.DockerRootDir}}'
docker ps -a
docker images
findmnt -T "$JETSTREAM_VOLUME_MOUNT/containerd"
```

Keep `/var/lib/containerd` until containers and images have been verified. After
a successful maintenance window and backup, remove the old root-disk copy to
recover space:

```bash
sudo systemctl stop docker.service docker.socket containerd.service
sudo mv /var/lib/containerd /var/lib/containerd.pre-jetstream
sudo mkdir -p /var/lib/containerd
sudo systemctl start containerd.service docker.service
# Verify containers and images again, then only when confident:
sudo rm -rf /var/lib/containerd.pre-jetstream
```

If the service fails, stop Docker/containerd, restore the previous config, and
move the saved directory back. Do not build the notebook image until this move
is complete.

## 3. Configure deployment secrets and paths

```bash
cd /home/exouser/AI4ScientificCoding
cp .env.example .env
chmod 600 .env
```

Generate three independent secrets:

```bash
openssl rand -hex 32  # POSTGRES_PASSWORD
openssl rand -hex 32  # LLM_GATEWAY_SIGNING_KEY
openssl rand -hex 32  # LLM_PSEUDONYMIZATION_KEY
```

Edit `.env` and set at least:

```bash
GITHUB_CLIENT_ID=...
GITHUB_CLIENT_SECRET=...
OAUTH_CALLBACK_URL=https://<hub-host>/hub/oauth_callback

JETSTREAM_VOLUME_MOUNT=/media/volume/SRP-JupyterHub
JETSTREAM_DATA_ROOT=/media/volume/SRP-JupyterHub/ai4scientificcoding

POSTGRES_PASSWORD=<first-random-value>
LLM_GATEWAY_SIGNING_KEY=<second-random-value>
LLM_PSEUDONYMIZATION_KEY=<third-random-value>
LLM_UPSTREAM_BASE_URL=https://llm.jetstream-cloud.org/v1
LLM_UPSTREAM_API_KEY=<provider-key>
LLM_DEPLOYMENT_ID=<course-and-semester>
LLM_CONSENT_VERSION=<approved-consent-version>
```

Keep the signing and pseudonymization keys stable when moving the deployment;
changing them invalidates active tokens and changes participant pseudonyms.

## 4. Prepare storage on the attached disk

```bash
set -a
source .env
set +a

[ "$(findmnt -n -o TARGET -T "$JETSTREAM_VOLUME_MOUNT")" = "$JETSTREAM_VOLUME_MOUNT" ]

mkdir -p   "$JETSTREAM_DATA_ROOT/users"   "$JETSTREAM_DATA_ROOT/research/postgres"   "$JETSTREAM_DATA_ROOT/research/backups"   "$JETSTREAM_DATA_ROOT/research/exports"

df -h "$JETSTREAM_DATA_ROOT"
```

The PostgreSQL image initializes and owns its database directory. JupyterHub
creates each user directory with mode `0700` and ownership `1000:100` just
before spawning that user.

## 5. Validate and build

Resolve Compose configuration before making changes:

```bash
docker network inspect jupyterhub-network >/dev/null 2>&1 ||   docker network create jupyterhub-network

docker compose --env-file .env -f compose.research.yaml config --quiet
```

Build the small gateway image and start PostgreSQL:

```bash
docker compose --env-file .env -f compose.research.yaml up -d --build

docker compose --env-file .env -f compose.research.yaml ps
docker compose --env-file .env -f compose.research.yaml logs --tail 100
```

Build the changed notebook and Hub images. Docker layer storage must already be
on the attached volume as checked above:

```bash
docker build   -f jupyterhub/Dockerfile.notebook   -t ai4scientificcoding-notebook:latest   .

docker build   -f jupyterhub/Dockerfile   -t jupyterhub-complete:latest   .
```

## 6. Preserve data from existing user containers

Existing containers predate the persistent bind mounts. For each user:

1. Ask the user to save work and stop their server through JupyterHub.
2. Confirm the old container is stopped.
3. Copy its work into the new Jetstream-backed directory.
4. Verify the copied files before removing the old container.

Example:

```bash
USER_NAME=github-user
OLD_CONTAINER=jupyter-$USER_NAME

docker inspect -f '{{.State.Running}}' "$OLD_CONTAINER"
./jupyterhub/migrate-user-storage.sh "$OLD_CONTAINER" "$USER_NAME"

sudo find "$JETSTREAM_DATA_ROOT/users/$USER_NAME"   -maxdepth 2 -type f -printf '%P
' | head -50

docker rm "$OLD_CONTAINER"
```

The migration helper refuses running containers, unsafe usernames, a non-mounted
data root, and nonempty destinations. It also migrates legacy assignments that
were stored outside `/home/jovyan/work`.

## 7. Replace the Hub container

After migrating every required user, replace the Hub so it loads the new config:

```bash
docker rm -f jupyterhub
./jupyterhub/start-jupyterhub.sh

docker logs jupyterhub --tail 100
```

`DockerSpawner.remove=True` now removes stopped notebook containers. User files
remain because `/home/jovyan/work` is a separate Jetstream bind mount.

## 8. Verify services and storage placement

```bash
docker compose --env-file .env -f compose.research.yaml ps

docker compose --env-file .env -f compose.research.yaml exec -T llm-gateway   python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8010/ready').read().decode())"

docker inspect interaction-db --format   '{{range .Mounts}}{{.Source}} -> {{.Destination}} rw={{.RW}}{{println}}{{end}}'

df -h "$JETSTREAM_DATA_ROOT"
du -sh "$JETSTREAM_DATA_ROOT/research/postgres"
```

The database source must begin with `JETSTREAM_DATA_ROOT`; it must not be a path
on `/dev/sda1`.

## 9. Verify a freshly spawned user

After the user signs in and starts a server:

```bash
USER_NAME=github-user
USER_CONTAINER=jupyter-$USER_NAME

docker inspect "$USER_CONTAINER" --format   '{{range .Mounts}}{{.Source}} -> {{.Destination}} rw={{.RW}}{{println}}{{end}}'

docker exec "$USER_CONTAINER" sh -lc '
  id
  stat -c "%A %u:%g %n" /home/jovyan/work
  test -w /home/jovyan/work
  printf "gateway=%s token_length=%s
"     "$OPENAI_BASE_URL" "${#OPENAI_API_KEY}"
  getent hosts llm-gateway
'
```

Expected results:

- `/home/jovyan/work` maps to `JETSTREAM_DATA_ROOT/users/<username>`.
- It is owned by `1000:100`, writable, and not shared with another user.
- The base URL is `http://llm-gateway:8010/v1`.
- A token exists, but the upstream provider key is absent.

## 10. End-to-end logging test

Send a recognizable non-streaming request from inside the user container:

```bash
docker exec "$USER_CONTAINER" bash -lc '
  curl -fsS "$OPENAI_BASE_URL/chat/completions"     -H "Authorization: Bearer $OPENAI_API_KEY"     -H "Content-Type: application/json"     -H "X-LLM-Client: deployment-test"     -d '''{
      "model": "Kimi-K2.6",
      "messages": [
        {"role": "user", "content": "RESEARCH_LOG_TEST_2026"}
      ]
    }'''
'
```

Compute that user's pseudonym and find the database row:

```bash
set -a
source .env
set +a
PARTICIPANT_ID=$(./jupyterhub/participant-id.py "$USER_NAME")

docker compose --env-file .env -f compose.research.yaml exec -T interaction-db   psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -x -c   "SELECT interaction_id, participant_id, deployment_id, client_name,
          request_started_at, status, upstream_status, model_requested,
          model_returned, duration_ms, prompt_tokens, completion_tokens,
          request_payload, response_payload
   FROM llm_interactions
   WHERE participant_id = '$PARTICIPANT_ID'
   ORDER BY request_started_at DESC
   LIMIT 1;"
```

Confirm that no GitHub username, authorization header, or upstream key appears in
the row.

### Streaming test

```bash
docker exec -it "$USER_CONTAINER" bash -lc '
  curl -N "$OPENAI_BASE_URL/chat/completions"     -H "Authorization: Bearer $OPENAI_API_KEY"     -H "Content-Type: application/json"     -H "X-LLM-Client: streaming-test"     -d '''{
      "model": "Kimi-K2.6",
      "stream": true,
      "messages": [{"role": "user", "content": "Count slowly from one to five."}]
    }'''
'
```

Chunks should appear progressively. The stored response payload will contain a
JSON `events` array rather than one opaque SSE string.

## 11. Test persistent user storage

```bash
TOKEN=$(openssl rand -hex 16)
docker exec "$USER_CONTAINER" sh -c   'printf "%s
" "$1" > /home/jovyan/work/persistence-test.txt' sh "$TOKEN"
```

Stop the server through JupyterHub. Because containers are now disposable, start
it again and verify:

```bash
docker exec "$USER_CONTAINER" cat /home/jovyan/work/persistence-test.txt
```

The value must match `$TOKEN`. Also verify the host copy:

```bash
sudo cat "$JETSTREAM_DATA_ROOT/users/$USER_NAME/persistence-test.txt"
```

## 12. Inspect research data

Counts by status and model:

```bash
docker compose --env-file .env -f compose.research.yaml exec -T interaction-db   psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c   "SELECT status, model_requested, count(*)
   FROM llm_interactions
   GROUP BY status, model_requested
   ORDER BY count(*) DESC;"
```

Recent requests without printing prompt bodies:

```bash
docker compose --env-file .env -f compose.research.yaml exec -T interaction-db   psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c   "SELECT interaction_id, left(participant_id, 12) AS participant,
          request_started_at, client_name, model_requested, status,
          upstream_status, round(duration_ms::numeric, 1) AS duration_ms
   FROM llm_interactions
   ORDER BY request_started_at DESC
   LIMIT 25;"
```

Inspect one interaction, including content:

```bash
INTERACTION_ID=<uuid>
docker compose --env-file .env -f compose.research.yaml exec -T interaction-db   psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -x -c   "SELECT * FROM llm_interactions WHERE interaction_id = '$INTERACTION_ID';"
```

Export research rows to CSV on the attached volume:

```bash
docker compose --env-file .env -f compose.research.yaml exec -T interaction-db   psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c   "\copy (SELECT * FROM llm_interactions ORDER BY request_started_at)
   TO STDOUT WITH CSV HEADER"   > "$JETSTREAM_DATA_ROOT/research/exports/llm_interactions.csv"
```

## 13. Back up and restore

Create a logical PostgreSQL backup on the attached volume:

```bash
BACKUP="$JETSTREAM_DATA_ROOT/research/backups/llm-research-$(date -u +%Y%m%dT%H%M%SZ).dump"
docker compose --env-file .env -f compose.research.yaml exec -T interaction-db   pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc > "$BACKUP"
ls -lh "$BACKUP"
```

A backup on the same volume protects against database corruption, not volume
loss. Copy backups to a second Jetstream volume or approved object storage.

Test restore into a separate database:

```bash
docker compose --env-file .env -f compose.research.yaml exec -T interaction-db   createdb -U "$POSTGRES_USER" llm_research_restore

docker compose --env-file .env -f compose.research.yaml exec -T interaction-db   pg_restore -U "$POSTGRES_USER" -d llm_research_restore < "$BACKUP"

docker compose --env-file .env -f compose.research.yaml exec -T interaction-db   psql -U "$POSTGRES_USER" -d llm_research_restore -c   'SELECT count(*) FROM llm_interactions;'
```

## Operational cautions

- Never mount `research/postgres` into notebook containers.
- Never expose PostgreSQL port 5432 publicly.
- Keep `.env` mode `0600` and out of Git.
- Treat prompts, responses, tool calls, and code as sensitive research data.
- Set `LLM_CAPTURE_CONTENT=false` when only operational metadata is approved.
- Establish consent, retention, deletion, and researcher-access procedures before
  collecting participant data.
- Monitor rows stuck in status `started`; they indicate an interrupted gateway
  process or unfinished request.
