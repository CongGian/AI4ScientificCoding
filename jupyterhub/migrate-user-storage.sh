#!/bin/bash
set -euo pipefail

if [ "$#" -ne 2 ]; then
  echo "Usage: $0 <stopped-container-name> <github-username>" >&2
  exit 2
fi

container=$1
username=$2
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd -- "${SCRIPT_DIR}/.." && pwd)
ENV_FILE=${ENV_FILE:-"${REPO_ROOT}/.env"}

set -a
source "${ENV_FILE}"
set +a

JETSTREAM_VOLUME_MOUNT=${JETSTREAM_VOLUME_MOUNT:-/media/volume/SRP-JupyterHub}
JETSTREAM_DATA_ROOT=${JETSTREAM_DATA_ROOT:-${JETSTREAM_VOLUME_MOUNT}/ai4scientificcoding}
destination=${JETSTREAM_DATA_ROOT}/users/${username}

if [ "$(findmnt -n -o TARGET -T "${JETSTREAM_DATA_ROOT}")" != "${JETSTREAM_VOLUME_MOUNT}" ]; then
  echo "Refusing migration: data root is not on the configured Jetstream mount." >&2
  exit 1
fi
if ! [[ "${username}" =~ ^[A-Za-z0-9][A-Za-z0-9-]{0,38}$ ]]; then
  echo "Unsafe GitHub username: ${username}" >&2
  exit 1
fi
if [ "$(docker inspect -f '{{.State.Running}}' "${container}")" != "false" ]; then
  echo "Stop ${container} through JupyterHub before copying its data." >&2
  exit 1
fi
if [ -e "${destination}" ] && [ -n "$(find "${destination}" -mindepth 1 -maxdepth 1 -print -quit)" ]; then
  echo "Destination is not empty: ${destination}" >&2
  exit 1
fi

mkdir -p "${destination}"
docker cp "${container}:/home/jovyan/work/." "${destination}/"

# Older images cloned assignments outside the persistent work directory.
mkdir -p "${destination}/assignments"
if docker cp "${container}:/home/jovyan/assignments/." "${destination}/assignments/" 2>/dev/null; then
  echo "Migrated legacy assignments directory."
fi

legacy_repo=${destination}/assignments/hw01-foundations
if [ -d "${legacy_repo}/.git" ]; then
  git -C "${legacy_repo}" remote set-url origin     https://github.com/NCSU-NNDL-Spring26/hw01-foundations
fi

sudo chown -R 1000:100 "${destination}"
sudo chmod 0700 "${destination}"

echo "Migrated ${container} to ${destination}"
echo "Verify the files, then remove the old stopped container with: docker rm ${container}"
