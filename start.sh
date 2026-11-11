#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# SwarMind — quick start
#   ./start.sh           first run: creates .env with random secrets, then starts everything
#   ./start.sh --down    stops the services (data is kept)
#   ./start.sh --logs    follows backend and worker logs
# The manual equivalent is in README.md (Quick start).
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail
cd "$(dirname "$0")"

info()  { printf '\033[0;32m[SwarMind]\033[0m %s\n' "$1"; }
error() { printf '\033[0;31m[ERROR]\033[0m %s\n' "$1" >&2; exit 1; }

case "${1:-}" in
  --down) docker compose down; info "Services stopped."; exit 0 ;;
  --logs) docker compose logs -f backend worker; exit 0 ;;
  "") ;;
  *) error "Unknown option: $1" ;;
esac

command -v docker >/dev/null || error "Docker not found: install Docker Engine (or Docker Desktop) with Compose v2."
docker compose version >/dev/null 2>&1 || error "Docker Compose v2 not found ('docker compose')."

# Random values without extra dependencies: openssl, or python3 from the standard library
random_b64url() {  # 32 random bytes, url-safe base64 (a valid Fernet key)
  if command -v openssl >/dev/null; then openssl rand -base64 32 | tr '+/' '-_'
  else python3 -c "import base64,os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())"; fi
}
random_hex() {
  if command -v openssl >/dev/null; then openssl rand -hex 24
  else python3 -c "import secrets; print(secrets.token_hex(24))"; fi
}
set_env() {  # set_env KEY VALUE: replaces the KEY= line of .env (values are [A-Za-z0-9_=-] only)
  local tmp; tmp="$(mktemp)"
  awk -v k="$1" -v v="$2" 'BEGIN{FS=OFS="="} $1==k {print k "=" v; next} {print}' .env > "$tmp" && mv "$tmp" .env
}

if [ ! -f .env ]; then
  info "Creating .env from .env.example with random secrets..."
  cp .env.example .env
  set_env ENCRYPTION_KEY "$(random_b64url)"
  set_env POSTGRES_PASSWORD "$(random_hex)"
  set_env CHROMA_TOKEN "$(random_hex)"
  chmod 600 .env
  info "Back up .env: without ENCRYPTION_KEY the stored provider keys cannot be decrypted."
fi

grep -Eq '^ENCRYPTION_KEY=.+' .env || error "ENCRYPTION_KEY is empty in .env (see .env.example)."

info "Building and starting the services (the first build takes a few minutes)..."
docker compose up -d --build

info "Waiting for the backend..."
for _ in $(seq 1 90); do
  if docker compose exec -T backend curl -sf http://localhost:5001/api/health >/dev/null 2>&1; then
    break
  fi
  sleep 2
done
docker compose exec -T backend curl -sf http://localhost:5001/api/health >/dev/null 2>&1 \
  || error "The backend is not answering. Check: docker compose logs backend"

cat <<'EOF'

SwarMind is running on http://localhost:3000

First time? Create the superadmin (the password is asked twice, hidden):
  docker compose exec backend flask --app run create-superadmin --email you@example.com

Then sign in and add an LLM provider key in Settings > AI providers.
To serve it on a domain, put a reverse proxy with TLS in front of port 3000:
see docs/manual/en/01-installation.md.
EOF
