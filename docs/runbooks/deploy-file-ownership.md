# Runbook: keep the repo free of root-owned files

> Conventions: `SWARMIND_DIR` is the folder of your checkout, the one with `docker-compose.yml` (for example `export SWARMIND_DIR=/opt/swarmind`). Commands run on the server as the user who owns that checkout. Volume names carry the Compose project name as prefix (the folder name by default, e.g. `swarmind_hf_cache`).

## Why

`backend` and `worker` run as root, and `./backend` is bind-mounted at `/app`. Anything they write in `/app` ends up in the checkout on the server, owned by root:

- `__pycache__/` folders, written whenever Python imports a module;
- `backend/migrations/versions/*.py`, if a migration is generated inside a container.

`git checkout` and `git pull`, run as the deploy user, then fail with `Permission denied` on those files. This has already happened once, with `backend/migrations/versions`.

Compose now sets `PYTHONDONTWRITEBYTECODE=1` for `backend` and `worker`, so Python no longer writes `__pycache__`. The container user is unchanged.

## Rules

1. **Create migrations locally, never inside a container.** Write or generate the migration file on your machine, commit it, and deploy it with `git pull`. Inside the container, only apply migrations:

   ```bash
   docker compose exec backend flask db upgrade
   ```

   Never run `flask db migrate` or `flask db revision` in a container: the new file would be root-owned in the repo.

2. **Check `git status` after every checkout or pull on the server.**

   ```bash
   cd "$SWARMIND_DIR"
   git pull && git checkout <branch> && git pull
   git status
   ```

   Expect `nothing to commit, working tree clean` (untracked local files such as `.env` are fine). A `Permission denied` error, or files you didn't change, means root-owned files are in the way. Apply the one-time fix below.

## One-time fix

Run this once on the server, after deploying the Compose change. It also cleans up anything written before the change.

```bash
cd "$SWARMIND_DIR"
sudo chown -R "$(id -un):$(id -gn)" backend
git status
```

Then recreate `backend` and `worker` so the new environment variable is applied. `docker compose restart` does not read Compose changes:

```bash
docker compose up -d backend worker
docker compose exec backend printenv PYTHONDONTWRITEBYTECODE   # expect: 1
docker compose exec worker printenv PYTHONDONTWRITEBYTECODE    # expect: 1
```

## Check that nothing new is root-owned

After a few simulations:

```bash
cd "$SWARMIND_DIR"
find backend -user root | head
```

Expect no output.
