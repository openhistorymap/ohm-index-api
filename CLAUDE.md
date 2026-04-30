# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

This sub-project is one of ~40 services in the Open History Map ecosystem rooted at `/srv/ohm`. The parent `/srv/ohm/CLAUDE.md` describes the broader service graph and shared infrastructure; this file documents only what is specific to `ohmi`.

## What this service is

`ohmi` (the "OHM Data Index API") is a small FastAPI + SQLModel service that mirrors a Zotero group library into a local SQLite file (`database.db`) and exposes it as an HTTP API. It is the bibliography / source-of-record index for the Open History Map project.

- Upstream of truth: Zotero group library **`3757017`** (the `OHM_LIB` constant in both `app/main.py` and `app/db.py`). The service is read-mostly; the only mutation endpoint is `POST`-less `GET /pull`, which wipes and rebuilds the SQLite DB from Zotero.
- Auth: requires `ZOTERO_KEY` in the environment for any path that talks to Zotero (everything except cached SQLite reads).
- Optional: `INDEX_TITLE` overrides the title shown in the OpenAPI doc (default `"Open History Map"`).

## Running

```bash
bash run.sh                 # python app/db.py  (rebuilds database.db)  then  uvicorn app.main:app --port 80 --host 0.0.0.0
docker build -t ohmi . && docker run -e ZOTERO_KEY=... -p 80:80 ohmi
```

`run.sh` is the only run-script in this directory and the Dockerfile invokes it. Note the `Dockerfile` ends with a lowercase `cmd "/srv/run.sh"` (shell form) — works, but is unusual.

There is an embedded Python virtualenv (`bin/`, `include/`, `lib/`, `share/`) committed alongside the source. Prefer `source bin/activate` over creating a fresh venv if you need to run things locally without Docker, since the committed venv was the one originally used to produce `database.db` and `dump.json`.

There are no tests.

## Architecture

Two files do all the work:

- **`app/db.py`** — SQLModel schema and the Zotero → SQLite ingestion. The module **constructs the SQLAlchemy engine at import time** (`engine = create_engine(sqlite_url, echo=True)`), so importing it from outside the project root will create / point at the wrong `database.db`. Always run from `/srv/ohm/ohmi`.
- **`app/main.py`** — FastAPI app exposing `/types`, `/tags`, `/template/{typ}`, `/pull`, `/index`, `/indices`, `/sources[/{id}]`, `/datasets[/{id}]`. Reads `topics.json`, `filetypes.json`, and `geonames.tree` from the working directory at request time, so again: run from the project root.

### Data model (`app/db.py`)

- `Research` — top-level Zotero items (no `parentItem`). Each has many `Tag` rows.
- `Tag` — flattened `key=value` Zotero tags into `(name, str_value, num_value)`. The Zotero tag convention used by OHM is `ohm:from_time=...`, `ohm:to_time=...`, `ohm:topic=...`, `ohm:area=geonames:<id>`, etc. `Tag.name`, `str_value`, and `num_value` are all indexed because the `/sources` endpoint filters by `Tag.name == 'ohm:from_time'` etc.
- `Dataset` — Zotero child items (those with `parentItem`), linked back via `parent_research`.
- `GeoLabel` / `GeoTree` — GeoNames hierarchy. `refresh_db()` walks every `ohm:area=geonames:<id>` tag, calls `api.geonames.org/hierarchyJSON?username=openhistorymap`, and stores both flat labels and a parent/children tree. The same tree is also written to `geonames.tree` on disk and re-read by `GET /indices`.

`refresh_db()` is destructive: it removes `database.db` and rebuilds from scratch. There is no incremental sync.

### Endpoints worth knowing

- `GET /pull` — runs `refresh_db()` synchronously. Slow; hits the Zotero API for every item plus GeoNames once per distinct area.
- `GET /index?ohm_area__in=<csv>&tags=<pipe-separated>` — produces `(year_bucket, topic) → {available, subs}` coverage counts. Pure SQLite; loads all `Tag` rows once and groups in Python (the dataset is small). An empty `ohm_area__in` means "no area filter".
- `GET /sources` — filters use correlated `EXISTS` subqueries against `Tag`, so multiple filters combine sanely (a single Tag row never has to satisfy two `name=...` constraints at once).
- `GET /indices` — returns a list of `{name, values, primary}` indicator descriptors (`years`, `topics`, `areas`, `trees`).

### Pre-computed `years` buckets

`app/main.py` defines a hard-coded list of `(from, to)` year ranges spanning ~9000 BCE to ~1900 CE with non-uniform bucket widths (1000-year, 500-year, 200-year). This is used by both `/index` (for time-bucketing) and `/indices`. If you change the schema, keep both endpoints in sync.

## Known caveats specific to this checkout

- `dump.json`, `database.db`, and `geonames.tree` may appear as untracked artifacts after a run — they are snapshots produced by `refresh_db()`, not source. Don't hand-edit or commit them; regenerate via `/pull` or `python app/db.py`.
- `geonames.tree` is both a generated artifact (written by `refresh_db()`) and a runtime input read by `/indices`. The format must remain a single nested-dict JSON object keyed by GeoNames IDs.
- `run.sh` always runs `python app/db.py` before starting uvicorn, which **destroys and rebuilds** `database.db` from Zotero. Container start without a working `ZOTERO_KEY` will leave the service with an empty SQLite file. There is no incremental sync.
- `requirements.txt` pins FastAPI 0.115 / Pydantic 2 / SQLModel 0.0.22 — modernized from the original 0.68 / Pydantic 1 baseline. If you touch any model or response_model, remember Pydantic v2 strict types: `Optional[X]` fields need an explicit `= None` default, and response shapes are validated, not coerced silently.
