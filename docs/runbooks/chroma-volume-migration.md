# Runbook: move Chroma data to a persistent volume

> Conventions: `SWARMIND_DIR` is the folder of your checkout, the one with `docker-compose.yml` (for example `export SWARMIND_DIR=/opt/swarmind`). Commands run on the server as the user who owns that checkout. Volume names carry the Compose project name as prefix (the folder name by default, e.g. `swarmind_hf_cache`).

**This is a deliberate, one-time exception to the "never restart Chroma" rule.** The fix cannot be applied without recreating the `swarmind-chroma` container.

## Why

`chromadb/chroma:1.0.21` stores its data in `/data`, but the old Compose file mounted the volume at `/chroma/chroma`. The data therefore lived in the container's writable layer and was lost whenever the container was recreated. That is how the project KB became empty on 2026-06-06.

This runbook:

- copies the current `/data` to a host folder
- fills a new volume, `<project>_chroma_data_v1`, from that copy
- recreates only Chroma on the new mount

The old volume `swarmind_chroma_data` is not touched. It may hold data in an older format.

## Before you start

- Run every command from `$SWARMIND_DIR`, in the same shell. If the shell dies, `export` the variables from step 0 again, using the same `BACKUP` folder.
- Expect the API to be down for a few minutes, from step 2 until step 8.
- Never run `docker compose down -v`.
- `docker compose restart` does not apply new mounts. Use the exact commands below.
- If any "Expect" line doesn't match, stop and go to [Rollback](#rollback).

## 0. Set variables and pre-flight checks

```bash
cd "$SWARMIND_DIR"
export BACKUP="$HOME/chroma-backup-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$BACKUP"
git rev-parse --abbrev-ref HEAD > "$BACKUP/prev_ref"
git rev-parse HEAD > "$BACKUP/prev_sha"
export PROJECT="$(docker inspect swarmind-chroma --format '{{index .Config.Labels "com.docker.compose.project"}}')"
export NEW_VOL="${PROJECT}_chroma_data_v1"
echo "BACKUP=$BACKUP PROJECT=$PROJECT NEW_VOL=$NEW_VOL prev_ref=$(cat "$BACKUP/prev_ref")"

git status --short
docker inspect swarmind-chroma --format 'user=[{{.Config.User}}]'
docker volume inspect "$NEW_VOL" >/dev/null 2>&1 && echo "STOP: $NEW_VOL already exists" || echo "ok: $NEW_VOL does not exist yet"
df -h "$HOME"

docker exec swarmind-postgres psql -U swarmind -d swarmind -At -c "SELECT source_file_path FROM projects;" </dev/null |
  while read -r f; do
    docker exec swarmind-worker test -f "$f" </dev/null && echo "source ok: $f" || echo "SOURCE MISSING: $f"
  done
```

Expect:

- `git status` lists no change to `docker-compose.yml`
- `user=[]`, meaning Chroma runs as root (step 5 relies on this)
- `ok: ... does not exist yet`
- every project prints `source ok`

A project with a missing source file can't have its KB rebuilt, and new simulations on it will fail at spawn because the Demographer needs the brief. Re-upload that project afterwards.

## 1. Confirm no simulation is running

```bash
docker exec swarmind-worker celery -A app.celery_app inspect active
docker exec swarmind-worker celery -A app.celery_app inspect reserved
docker exec swarmind-redis redis-cli llen celery
docker exec swarmind-postgres psql -U swarmind -d swarmind -c \
  "SELECT id, status, current_round, started_at FROM simulations WHERE status IN ('BUILDING_GRAPH','SPAWNING_AGENTS','RUNNING','GENERATING_REPORT');"
```

Expect: `active` and `reserved` both report `empty` for the worker, and `llen` is `0`.

The SQL query can show old rows left in a stale status. Those are fine if Celery reports nothing active. If a task is active, wait for it to finish.

## 2. Stop new work and record collection counts

Stopping the backend prevents new tasks. The worker stays up, idle, so it can run the counts.

```bash
docker compose stop backend

cat > "$BACKUP/chroma_counts.py" <<'PY'
import os
from app.memory.agent_memory import get_chroma

c = get_chroma(os.environ["CHROMA_HOST"], int(os.environ["CHROMA_PORT"]), os.environ.get("CHROMA_TOKEN", ""))
cols = c.list_collections()
assert len(cols) == c.count_collections(), "collection listing is incomplete"
for name, count in sorted((col.name, col.count()) for col in cols):
    print(f"{name}\t{count}")
PY

docker exec -i swarmind-worker python - < "$BACKUP/chroma_counts.py" > "$BACKUP/counts_before.tsv"
wc -l "$BACKUP/counts_before.tsv"
grep '^kb_project_' "$BACKUP/counts_before.tsv"
```

Expect: the line count matches the known number of collections (93 when this runbook was written), and the KB line shows `count` 0.

## 3. Stop Chroma and back up `/data`

Chroma must be stopped so the SQLite file is consistent.

```bash
docker compose stop chroma
docker cp swarmind-chroma:/data "$BACKUP/data"
ls -la "$BACKUP/data" | head -20
test -f "$BACKUP/data/chroma.sqlite3" && echo "backup ok" || echo "STOP: chroma.sqlite3 missing"
du -sh "$BACKUP/data"
```

Expect: `backup ok`.

## 4. Create the new volume

The labels make Compose treat the volume as its own, so it prints no ownership warning.

```bash
docker volume create \
  --label com.docker.compose.project="$PROJECT" \
  --label com.docker.compose.volume=chroma_data_v1 \
  "$NEW_VOL"
```

## 5. Fill the new volume from the backup

This uses the `redis:7-alpine` image already on the host, so nothing is pulled.

```bash
docker run --rm -v "$NEW_VOL":/dst -v "$BACKUP/data":/src:ro --entrypoint sh redis:7-alpine \
  -c 'cp -a /src/. /dst/ && chown -R 0:0 /dst'

echo "files in backup: $(find "$BACKUP/data" | wc -l)"
docker run --rm -v "$NEW_VOL":/dst:ro --entrypoint sh redis:7-alpine -c 'echo "files in volume: $(find /dst | wc -l)"; ls -la /dst | head'
```

Expect: the two file counts are equal.

## 6. Pull the branch

```bash
git fetch origin
git checkout fix/chroma-kb-persistence
git pull --ff-only
grep -n 'chroma_data_v1:/data' docker-compose.yml
```

Once the PR is merged, use the normal `main` or `dev` checkout here instead.

Expect: `grep` prints the mount line.

## 7. Recreate only Chroma on the new mount and compare counts

```bash
docker compose up -d --no-deps --force-recreate chroma
for i in $(seq 1 60); do curl -sf http://127.0.0.1:8001/api/v2/heartbeat >/dev/null && { echo "chroma up"; break; }; sleep 1; done

docker inspect swarmind-chroma --format '{{range .Mounts}}{{.Name}} -> {{.Destination}}{{"\n"}}{{end}}'
docker exec -i swarmind-worker python - < "$BACKUP/chroma_counts.py" > "$BACKUP/counts_after.tsv"
diff "$BACKUP/counts_before.tsv" "$BACKUP/counts_after.tsv" && echo "COUNTS MATCH" || echo "STOP: COUNTS DIFFER"
docker diff swarmind-chroma | grep ' /data' || echo "no /data writes in the container layer"
```

Expect:

- the mount shows `<project>_chroma_data_v1 -> /data`
- `COUNTS MATCH`
- `no /data writes in the container layer`

## 8. Prove the data survives a recreate

This is the exact event that lost the KB in June.

```bash
docker compose up -d --no-deps --force-recreate chroma
for i in $(seq 1 60); do curl -sf http://127.0.0.1:8001/api/v2/heartbeat >/dev/null && { echo "chroma up"; break; }; sleep 1; done
docker exec -i swarmind-worker python - < "$BACKUP/chroma_counts.py" > "$BACKUP/counts_after_recreate.tsv"
diff "$BACKUP/counts_before.tsv" "$BACKUP/counts_after_recreate.tsv" && echo "COUNTS MATCH AFTER RECREATE" || echo "STOP: COUNTS DIFFER"
```

Expect: `COUNTS MATCH AFTER RECREATE`.

## 9. Start the backend and recreate the worker

The worker must be recreated, not just restarted, to pick up the new `chroma_onnx_cache` mount. Postgres, Redis, Chroma and Flower are not touched.

```bash
docker compose up -d --no-deps --force-recreate backend worker
docker compose ps
curl -sf http://127.0.0.1:5001/api/health && echo " backend ok"
docker inspect swarmind-worker --format '{{range .Mounts}}{{.Destination}}{{"\n"}}{{end}}' | grep '/root/.cache/chroma'
```

Expect: `backend ok`, and the `grep` prints the cache path.

## 10. Check a real simulation

The KB stays at 0 until the first simulation starts: `spawn_agents_task` refills it then, using embeddings only, with no LLM calls. Start a small simulation from the UI, then run:

```bash
docker compose logs --no-log-prefix --since 15m worker 2>&1 > "$BACKUP/first_run.log"
grep -E 'kb_reingested|kb_source_missing|kb_reingest_failed|kb_empty|memories_seed_failed|memories_seeded' "$BACKUP/first_run.log" | cut -c1-200
echo "kb_retrieve_for_agent: $(grep -c kb_retrieve_for_agent "$BACKUP/first_run.log")"
echo "POST /query: $(grep -cE 'POST .*/collections/[0-9a-f-]+/query' "$BACKUP/first_run.log")"
docker exec -i swarmind-worker python - < "$BACKUP/chroma_counts.py" | grep '^kb_project_'
```

Expect:

- one `kb_reingested` line with a chunk count
- `memories_seeded`, and no `kb_empty` or `memories_seed_failed`
- `kb_retrieve_for_agent` and `POST /query` both above 0
- a KB count above 0

A second simulation on the same project must not log `kb_reingested` again.

## Rollback

### A. Before step 7 (the old container still exists)

Nothing has been lost. `start` reuses the existing container and its data.

```bash
git checkout "$(cat "$BACKUP/prev_ref")"
docker compose start chroma backend
```

Then check that the backend responds. Leave `$NEW_VOL` in place, and remove it only once you've decided not to retry.

### B. From step 7 on, counts differ or Chroma won't start

**The old container's `/data` no longer exists, so `$BACKUP/data` is the only copy.**

First, you can retry onto the new volume. This keeps the fix:

```bash
docker compose stop chroma
docker run --rm -v "$NEW_VOL":/dst -v "$BACKUP/data":/src:ro --entrypoint sh redis:7-alpine \
  -c 'find /dst -mindepth 1 -delete && cp -a /src/. /dst/ && chown -R 0:0 /dst'
docker compose up -d --no-deps --force-recreate chroma
```

Then repeat the checks in step 7.

To go back to the previous setup instead:

```bash
docker compose stop backend worker chroma
git checkout "$(cat "$BACKUP/prev_ref")"

# Create a container on the old mount, then restore /data into its layer while it is stopped
docker compose up -d --no-deps --force-recreate chroma
docker compose stop chroma
docker cp "$BACKUP/data/." swarmind-chroma:/data/
docker compose start chroma
for i in $(seq 1 60); do curl -sf http://127.0.0.1:8001/api/v2/heartbeat >/dev/null && { echo "chroma up"; break; }; sleep 1; done

docker compose up -d --no-deps --force-recreate backend worker
docker exec -i swarmind-worker python - < "$BACKUP/chroma_counts.py" > "$BACKUP/counts_rollback.tsv"
diff "$BACKUP/counts_before.tsv" "$BACKUP/counts_rollback.tsv" && echo "ROLLBACK COUNTS MATCH" || echo "COUNTS DIFFER: investigate before using the system"
```

This returns to the old state, where the data is still not persistent. Keep `$BACKUP` and `$NEW_VOL` for diagnosis.

## Afterwards

- **Merge the PR promptly.** While the server runs a branch with this change, don't check out a branch without this Compose change and run `docker compose up`. That would put Chroma back on the old mount, and it would look empty.
- **Keep `$BACKUP`** until you've seen a good simulation, then delete it.
- **Don't delete `swarmind_chroma_data`** as part of this work.
- **Old simulations ran without KB context.** Compare results only against runs made after this deploy.
