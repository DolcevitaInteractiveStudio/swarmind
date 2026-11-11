# Runbook: delete old agent-memory collections from Chroma

> Conventions: `SWARMIND_DIR` is the folder of your checkout, the one with `docker-compose.yml` (for example `export SWARMIND_DIR=/opt/swarmind`). Commands run on the server as the user who owns that checkout. Volume names carry the Compose project name as prefix (the folder name by default, e.g. `swarmind_hf_cache`).

One-off cleanup of the `sim_*` collections left on the Chroma server. Until `fix/chroma-stability`, every simulation created one collection per agent (`sim_<sim>_agent_<agent>`, about 20 per run) and never deleted them: 255 of them on 2026-11-08, next to 1 KB collection.

After this fix:

- each simulation has a single collection, `sim_<sim>_memory`
- that collection is deleted when the simulation reaches COMPLETED, FAILED or STOPPED
- a sweep 3 minutes after every worker start deletes any that were missed

Nothing reads agent memories after the rounds. The report and the agent chat use the persona fields in `agents.json`. So old collections can be deleted without losing anything a user can see.

The command:

- deletes only `sim_*` collections whose simulation is closed or no longer in the database
- never deletes `kb_*` collections
- never deletes a collection of a simulation that is PENDING or running
- stops without deleting anything if it can't read simulation statuses from Postgres
- runs in batches, with a pause between batches, and logs every deletion (`chroma_cleanup_deleted`)

## Before you start

- Deploy `fix/chroma-stability` first. The command ships with it.
- Run every command from `$SWARMIND_DIR`, in the same shell. If the shell dies, `export` the variables from step 0 again, using the same `BACKUP` folder.
- The API is down only during the backup in step 3, usually under a minute.
- Never run `docker compose down -v`.
- If any "Expect" line doesn't match, stop and go to [Rollback](#rollback).

## 0. Set variables

```bash
cd "$SWARMIND_DIR"
export BACKUP="$HOME/chroma-cleanup-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$BACKUP"
export VOL="$(docker inspect swarmind-chroma --format '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Name}}{{end}}{{end}}')"
echo "BACKUP=$BACKUP VOL=$VOL"
git log --oneline -1
df -h "$HOME"
```

Expect:

- `VOL` ends in `_chroma_data_v1`
- the commit is the deployed `fix/chroma-stability` (or the merge that contains it)
- enough free space for a copy of `/data`, which was about 52 MB on 2026-11-08

## 1. Confirm no simulation is running

```bash
docker exec swarmind-worker celery -A app.celery_app inspect active
docker exec swarmind-worker celery -A app.celery_app inspect reserved
docker exec swarmind-redis redis-cli llen celery
```

Expect: `active` and `reserved` both report `empty`, and `llen` is `0`.

The command protects running simulations anyway. This check is for the backup: Chroma is stopped in step 3.

## 2. Record collection counts

```bash
cat > "$BACKUP/chroma_counts.py" <<'PY'
from app.memory.chroma_client import get_chroma

c = get_chroma()
cols = c.list_collections()
assert len(cols) == c.count_collections(), "collection listing is incomplete"
for name, count in sorted((col.name, col.count()) for col in cols):
    print(f"{name}\t{count}")
PY

docker exec -i swarmind-worker python - < "$BACKUP/chroma_counts.py" > "$BACKUP/counts_before.tsv"
echo "total: $(wc -l < "$BACKUP/counts_before.tsv")  kb_*: $(grep -c '^kb_' "$BACKUP/counts_before.tsv")  sim_*: $(grep -c '^sim_' "$BACKUP/counts_before.tsv")"
grep '^kb_' "$BACKUP/counts_before.tsv"
```

Expect: about 256 in total, 1 `kb_*` with a count above 0, and the rest `sim_*`.

## 3. Back up `/data` with Chroma stopped

Chroma must be stopped so the SQLite file is consistent. Stopping the backend first means no new simulation starts in the meantime.

```bash
docker compose stop backend
docker compose stop chroma
docker cp swarmind-chroma:/data "$BACKUP/data"
test -f "$BACKUP/data/chroma.sqlite3" && echo "backup ok" || echo "STOP: chroma.sqlite3 missing"
du -sh "$BACKUP/data"
echo "files in backup: $(find "$BACKUP/data" | wc -l)"

docker compose start chroma
for i in $(seq 1 60); do curl -sf http://127.0.0.1:8001/api/v2/heartbeat >/dev/null && { echo "chroma up"; break; }; sleep 1; done
docker compose start backend
docker exec -i swarmind-worker python - < "$BACKUP/chroma_counts.py" | diff "$BACKUP/counts_before.tsv" - && echo "COUNTS MATCH"
```

Expect: `backup ok`, `chroma up`, `COUNTS MATCH`.

## 4. Dry run

```bash
docker exec swarmind-worker flask --app app chroma-cleanup --dry-run | tee "$BACKUP/dry_run.txt"
echo "to delete: $(grep -c '^  delete  ' "$BACKUP/dry_run.txt")"
grep '^  delete  ' "$BACKUP/dry_run.txt" | grep -v '^  delete  sim_' || echo "only sim_* listed"
grep '^  keep  ' "$BACKUP/dry_run.txt" || echo "nothing protected"
```

Expect:

- the `collections:` line shows the same totals as step 2 (log lines from the app start may come before it)
- `only sim_* listed`
- `to delete` equals the `sim_*` count from step 2, unless a simulation was started since then; those are listed under `keep`

The dry run deletes nothing. If the database is not reachable the command stops with an error before deleting anything (it never deletes without simulation statuses): fix the connection first.

## 5. Run

Batches of 10 with a 2-second pause between batches. About 255 collections take under 2 minutes.

```bash
docker exec swarmind-worker flask --app app chroma-cleanup --batch-size 10 --pause 2 | tee "$BACKUP/run.txt"
tail -1 "$BACKUP/run.txt"
```

Expect: the last line reads `done: N deleted, 0 failed`, where N is the `to delete` count from step 4.

A failed deletion is logged (`chroma_cleanup_failed`), skipped, and the command exits with status 1. Running it again retries only what is left.

## 6. Verify

```bash
docker exec -i swarmind-worker python - < "$BACKUP/chroma_counts.py" > "$BACKUP/counts_after.tsv"
echo "total: $(wc -l < "$BACKUP/counts_after.tsv")  kb_*: $(grep -c '^kb_' "$BACKUP/counts_after.tsv")  sim_*: $(grep -c '^sim_' "$BACKUP/counts_after.tsv")"
diff <(grep '^kb_' "$BACKUP/counts_before.tsv") <(grep '^kb_' "$BACKUP/counts_after.tsv") && echo "KB UNCHANGED"
docker compose logs --no-log-prefix --since 15m worker 2>/dev/null | grep -c chroma_cleanup_deleted
docker exec swarmind-chroma sh -c 'du -sh /data; ls /data | wc -l'
```

Expect:

- `sim_*` is 0, or only the collections listed as `keep` in step 4
- `KB UNCHANGED`

`du` may not shrink right away. Chroma frees space in its own time and the SQLite file does not shrink on delete. Rely on the counts.

Then start a small simulation from the UI and check its log:

```bash
docker compose logs --no-log-prefix --since 15m worker 2>&1 | grep -E 'memories_seeded|memories_seed_failed|memory_(store|read)_failed|memory_collection_deleted|chroma_unavailable' | cut -c1-200
```

Expect:

- `memories_seeded`
- no `memories_seed_failed`, `memory_*_failed` or `chroma_unavailable`
- `memory_collection_deleted` after the report

## Rollback

A deleted collection can only come back by restoring the whole of `/data` from step 3. Anything written to Chroma after step 3 is lost, including KB rebuilds and memories of simulations run since. The KB is rebuilt automatically at the next spawn.

```bash
docker compose stop backend worker chroma
docker run --rm -v "$VOL":/dst -v "$BACKUP/data":/src:ro --entrypoint sh redis:7-alpine \
  -c 'find /dst -mindepth 1 -delete && cp -a /src/. /dst/ && chown -R 0:0 /dst'
docker compose start chroma
for i in $(seq 1 60); do curl -sf http://127.0.0.1:8001/api/v2/heartbeat >/dev/null && { echo "chroma up"; break; }; sleep 1; done
docker compose start backend worker
docker exec -i swarmind-worker python - < "$BACKUP/chroma_counts.py" > "$BACKUP/counts_rollback.tsv"
diff "$BACKUP/counts_before.tsv" "$BACKUP/counts_rollback.tsv" && echo "ROLLBACK COUNTS MATCH"
```

Expect: `ROLLBACK COUNTS MATCH`.

## Afterwards

- Keep `$BACKUP` for a week, then delete it.
- No further manual cleanup should be needed. If `sim_*` collections pile up again, look in the worker log for `memory_collection_delete_failed` and `memory_sweep_failed`.
