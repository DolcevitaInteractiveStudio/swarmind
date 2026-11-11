# Runbook: rebuild the backend, worker and Flower images

> Conventions: `SWARMIND_DIR` is the folder of your checkout, the one with `docker-compose.yml` (for example `export SWARMIND_DIR=/opt/swarmind`). Commands run on the server as the user who owns that checkout. Volume names carry the Compose project name as prefix (the folder name by default, e.g. `swarmind_hf_cache`).

## Why and when

`backend`, `worker` and `flower` are built from `backend/Dockerfile`. The images only hold the Python packages: `backend` and `worker` run the code from the bind-mounted `./backend`, while Flower runs the code baked into its image.

Rebuild when `backend/requirements.txt`, `backend/constraints.txt` or `backend/Dockerfile` change. The first rebuild after dropping `sentence-transformers` takes each image from about 9.5 GB to about 1.6 GB, because torch, CUDA/nvidia, triton, transformers, scikit-learn and scipy are gone.

`kombu` is pinned (`kombu==5.6.2` with `redis==5.0.8`), so the old warning against rebuilding no longer applies. `constraints.txt` pins every transitive package, so a rebuild installs the same versions the worker was tested with.

**Never touch** `chroma`, `postgres`, `redis` or the volumes `hf_cache`, `chroma_data_v1`, `chroma_onnx_cache` (nor `postgres_data`, `redis_data`, `simulation_data`, `uploads`). Every command below names its services and uses `--no-deps`. Never run `docker compose down`, `docker volume prune` or `docker system prune --volumes`.

All commands run on the server as the deploy user, from `$SWARMIND_DIR`.

## 1. Pre-checks

```bash
cd "$SWARMIND_DIR"
git fetch origin
git checkout main && git pull        # or the branch being deployed
git status                           # expect a clean tree (untracked .env is fine)
git log --oneline -1                 # note the commit; the previous one is the code rollback target
```

Free disk: the build needs about 2 GB (the three images share their layers), and the old images stay until step 9.

```bash
df -h /var/lib/docker /               # want at least 5 GB free
docker system df
```

No simulation running. Recreating the worker stops the tasks it is running:

```bash
docker compose exec worker celery -A app.celery_app inspect active
# expect "- empty -" for the node; otherwise wait for the simulation to finish
```

## 2. Tag the current images for rollback

```bash
cd "$SWARMIND_DIR"
STAMP=$(date +%Y%m%d-%H%M)
echo "$STAMP" > ~/.swarmind-rollback-stamp
for s in backend worker flower; do
  img=$(docker inspect --format '{{.Image}}' swarmind-$s)
  docker image tag "$img" swarmind-$s:rollback-$STAMP
done
docker images | grep rollback-$STAMP
docker compose config --images     # image names Compose uses; expected swarmind-backend, swarmind-worker, swarmind-flower
```

If `config --images` prints other names, use those names in place of `swarmind-<service>:latest` in steps 8 and 9.

## 3. Build

```bash
cd "$SWARMIND_DIR"
time docker compose build --pull backend worker flower
docker compose images backend worker flower   # still the old images: build does not recreate containers
docker image ls --format '{{.Repository}}:{{.Tag}} {{.Size}}' | grep '^swarmind-'
```

Expect about 1.6 GB per image. A failed build leaves the running containers untouched: stop here and keep the old images.

## 4. Migrations (only if needed)

Check whether the database is behind the code:

```bash
docker compose exec backend flask --app run db current
docker compose exec backend flask --app run db heads
```

Only if `current` shows an older revision than the head, apply the migrations (never `db migrate` or `db revision` in a container, see `deploy-file-ownership.md`):

```bash
docker compose exec backend flask --app run db upgrade
```

If `current` prints no revision at all, the schema was made by `create_all` and never stamped: do not run `db upgrade` (it would re-apply migrations the schema already has). Stop and check the schema first.

## 5. Recreate the three containers on the new images

```bash
cd "$SWARMIND_DIR"
docker compose up -d --no-deps backend worker flower
docker compose ps backend worker flower        # backend becomes "healthy" within ~1 minute
```

`--no-deps` keeps postgres, redis and chroma running untouched. `up -d` (not `restart`) also applies Compose changes, for example `DATABASE_URL` for Flower.

## 6. Checks

```bash
cd "$SWARMIND_DIR"
# Worker answers
docker compose exec worker celery -A app.celery_app inspect ping            # expect: pong, 1 node online

# API
curl -fsS http://127.0.0.1:5001/api/health; echo                            # expect HTTP 200 and JSON

# No root-owned bytecode in the repo
docker compose exec backend printenv PYTHONDONTWRITEBYTECODE                # expect: 1
docker compose exec worker printenv PYTHONDONTWRITEBYTECODE                 # expect: 1

# KB embedder is e5 (model from the hf_cache volume)
docker compose exec worker python -c "from app.memory.kb_embedding import get_kb_embedder; print(type(get_kb_embedder()).__name__)"
# expect: E5KbEmbedder   (DefaultKbEmbedder means the e5 files are missing: check the hf_cache volume)

# torch and sentence-transformers are gone
docker compose exec worker python -c "import importlib.util as u; print(u.find_spec('torch'), u.find_spec('sentence_transformers'))"
# expect: None None

# Echo-chamber metric embeds with Chroma's ONNX model (from the chroma_onnx_cache volume)
docker compose exec worker python -c "
from app.report.metrics import compute_echo_chamber_index as f
feed = [{'round': r, 'content': t} for r in range(3) for t in ('The new monthly price looks high for a small shop', 'The new plan really helps beginners get started')]
print(f(feed)['method'])"
# expect: embedding   (fallback_jaccard means the ONNX model did not load: look for metric_embedding_failed in the output)

# Flower
curl -fsS http://127.0.0.1:5555/healthcheck; echo                           # expect: OK

# Startup logs: no crash, no schema errors
docker compose logs --since 10m backend worker flower | grep -E 'Traceback|UniqueViolation|Exception in worker process' || echo "no errors"
docker compose logs --since 10m backend | grep schema_init | tail -2          # expect fresh_database=False
```

## 7. One test simulation

From the UI, as the superadmin: a small simulation on an existing project with a built graph, for example 10 agents and 3 rounds, `google/gemini-2.5-flash` as fast model. It must reach COMPLETED and its report must contain the "Dinamiche del Dibattito" section with an echo-chamber value.

Then:

```bash
cd "$SWARMIND_DIR"
docker compose logs --since 30m worker | grep -E 'metric_embedding_(fallback|failed)|kb_embedding_fallback|Traceback' || echo "clean"
docker compose logs --since 30m backend | grep -E 'quota_period_reset' | tail -5   # first check of each user in a new period
```

If everything is fine, the deploy is done. Keep the rollback tags for a few days, then go to step 9.

## 8. Rollback

The images and the code go back together: the old code imports `sentence_transformers`, which is no longer in the new images.

```bash
cd "$SWARMIND_DIR"
STAMP=$(cat ~/.swarmind-rollback-stamp)
git checkout <previous commit noted in step 1>
for s in backend worker flower; do
  docker image tag swarmind-$s:rollback-$STAMP swarmind-$s:latest
done
docker compose up -d --no-deps --no-build backend worker flower
docker compose ps backend worker flower
docker compose exec worker celery -A app.celery_app inspect ping
curl -fsS http://127.0.0.1:5001/api/health; echo
```

`--no-build` makes Compose use the retagged images as they are. The new code also runs on the old images (they have every package it needs), so to roll back only the images, skip the `git checkout`.

After a rollback, go back to `main` with `git checkout main` once the cause is fixed, and run this runbook again.

## 9. Prune the old images (a few days later)

Only after the new images have run without problems:

```bash
cd "$SWARMIND_DIR"
STAMP=$(cat ~/.swarmind-rollback-stamp)
docker image rm swarmind-backend:rollback-$STAMP swarmind-worker:rollback-$STAMP swarmind-flower:rollback-$STAMP
docker image prune -f                          # dangling images only, never volumes
docker builder prune -f --filter until=168h    # build cache older than a week
docker system df
df -h /var/lib/docker
```

Do not use `docker system prune` or `docker volume prune`: the volumes hold the database, the Chroma data and the model caches.
