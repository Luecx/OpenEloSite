# Client/Server Simplification

## Current problems

- The client exposes a config-first workflow with `init-config`, `register`, `heartbeat`, `run`, and `status`, although the runtime only needs a small set of startup arguments.
- The client repository still contains bundled books, example workloads, and embedded `fastchess` source trees.
- `fast-chess` is staged into each workload directory instead of being managed once for the whole client workdir.
- Match jobs are pre-split in the database and contain legacy fields from rating lists, approvals, ownership, and capability tables.
- The server currently stores much more metadata than the runtime needs.

## Target client

The client should be a single runtime process started with a small set of arguments:

```text
client run --server http://server:8000 --access-key <token> --threads 16 --hash 8192 --workdir ./workdir
```

Required startup inputs:

- `server`
- `access_key`
- `max_threads`
- `max_hash`
- `workdir`

Optional:

- `machine_name`
- `heartbeat_interval_seconds`
- `poll_interval_seconds`

The client owns the full `workdir` and may create:

```text
workdir/
  fast-chess
  books/
  jobs/
```

No checked-in `bin/`, `tools/`, example workloads, or bundled `fastchess` sources should remain in the client tree.

## Client startup behavior

On startup the client does exactly this:

1. Resolve and create `workdir`.
2. Check whether `fast-chess` is available in `PATH`.
3. If not available in `PATH`, check `workdir/fast-chess`.
4. If still missing, clone and build `fastchess` inside `workdir`, then place the binary at `workdir/fast-chess`.
5. Check whether Docker is installed and the daemon is reachable.
6. Register with the server.
7. Enter the main loop: heartbeat, request job, run job, upload result, repeat.

If Docker is missing or not usable, the client exits with an error.

## Required runtime API

The runtime only needs four API areas:

1. Client registration
2. Heartbeat
3. Job assignment
4. Artifact transfer and result upload

### 1. Register

`POST /api/client/register`

Request:

```json
{
  "machine_key": "stable-local-id",
  "machine_name": "worker-01",
  "max_threads": 16,
  "max_hash": 8192,
  "cpu_flags": ["sse4", "avx2"]
}
```

Response:

```json
{
  "client_id": 12,
  "heartbeat_interval_seconds": 15,
  "poll_interval_seconds": 5
}
```

### 2. Heartbeat

`POST /api/client/heartbeat`

Request:

```json
{
  "client_id": 12,
  "state": "idle",
  "running_job_id": null
}
```

`state` should be one of:

- `idle`
- `running`
- `error`

The server determines active vs. inactive from `last_seen_at` plus a TTL. That is enough for online status.

### 3. Request next job

`POST /api/client/jobs/next`

Request:

```json
{
  "client_id": 12
}
```

Response without work:

```json
{
  "job": null
}
```

Response with work:

```json
{
  "job": {
    "job_id": 4711,
    "matchup_id": 88,
    "time_control": "60+1",
    "opening_book": {
      "name": "default-book",
      "hash": "abc123",
      "source": "/api/client/books/5"
    },
    "engine_1": {
      "name": "Engine A",
      "compile_command": "make build",
      "executable_path": "./bin/engine-a"
    },
    "engine_2": {
      "name": "Engine B",
      "compile_command": "make build",
      "executable_path": "./bin/engine-b"
    },
    "hash_per_engine": 64,
    "threads_per_engine": 1,
    "num_games": 256,
    "seed": 123456789
  }
}
```

`compile_command` is responsible for fetching sources as needed, for example via `git clone`.

### 4. Book transfer

The job only contains:

- `book_name`
- `book_hash`
- `book_source`

The client checks `workdir/books` for a file with matching name and hash.

If the book is missing, the client requests `book_source` from the server and stores it locally.

The client should treat `book_source` as opaque. It can be a relative API path now and a signed URL later.

### 5. Complete job

`POST /api/client/jobs/{job_id}/complete`

Request:

```json
{
  "status": "completed",
  "wins": 100,
  "draws": 120,
  "losses": 36,
  "pgn": "[Event ...]",
  "runtime_seconds": 587
}
```

If execution fails:

```json
{
  "status": "failed",
  "error": "compile failed"
}
```

## Client execution model

For each assigned job the client:

1. Ensures the opening book is present.
2. Materializes both engine sources in a job directory.
3. Runs both compile commands.
4. Verifies both executable paths.
5. Computes:

```text
concurrency = floor(client.max_threads / job.threads_per_engine)
```

6. Starts `fast-chess` with:

- time control
- opening book
- both executables
- `hash_per_engine`
- `threads_per_engine`
- `concurrency`
- `num_games`
- `seed`

7. Parses the `fast-chess` output.
8. Uploads `wins`, `draws`, `losses`, and combined PGN.

## Simplified server model

### User

Keep:

- identity and auth fields

Add or keep:

- a relation that answers: which engines may this user edit?

Remove runtime coupling from the engine side. The engine does not need owner columns.

### Engine

Keep:

- `id`
- `name`
- `slug`
- `description`
- `protocol`
- timestamps

Remove:

- `visibility`
- `status`
- `approval_status`
- `license_name`
- `repo_url`
- `website_url`
- `created_by_user_id`
- `primary_owner_id`

### Engine version

Keep:

- `engine_id`
- `version_name`
- `compile_command`
- `executable_path`
- `requires_*`
- timestamps

Remove:

- `status`
- `supported_platforms`
- `supports_linux`
- `supports_macos`
- `supports_windows`
- `branch_name`
- `commit_hash`
- `release_name`
- `source_hash`
- `approval_status`
- `notes`

`compiler` should also disappear if `compile_command` already fully defines the build.

### Opening book

Keep:

- `id`
- `name`
- `file_name`
- `file_path`
- `content_hash`

Optional:

- `description`

### Rating list

Keep only the data needed to define a playable pool:

- `id`
- `name`
- `description`
- `time_control`
- `threads_per_engine`
- `hash_per_engine`
- `opening_book_id`

Remove:

- `is_public`
- `is_active`
- `book_seed`
- `games_per_assignment`

`games_per_assignment` moves out of the database and into the scheduler.

### Client

Keep:

- `id`
- `user_id`
- `machine_key`
- `machine_name`
- `max_threads`
- `max_hash`
- `cpu_flags`
- `last_seen_at`

Optional:

- `last_state`

Remove:

- `display_name`
- `status`
- `pools_allowed`
- snapshot tables
- capability tables
- log tables

### Matchup and assignment

Replace the pre-split workload queue with two levels:

- `matchups`
- `assignments`

`matchups` define the long-running pairing:

- engine version A
- engine version B
- rating list
- cumulative wins/draws/losses
- cumulative PGN

`assignments` are created on demand for a client:

- `matchup_id`
- `client_id`
- `threads_per_engine`
- `hash_per_engine`
- `num_games`
- `seed`
- `status`
- `wins`
- `draws`
- `losses`
- `pgn`
- timestamps

This removes:

- pre-generated `games_per_workload`
- pre-generated `games_per_assignment`
- `book_seed`
- build jobs as a separate job type

## Matchmaker

The scheduler should no longer keep a large queue of pre-built workloads.

Instead:

1. Find active idle clients.
2. For each client, find compatible matchups.
3. Pick one matchup, initially random.
4. Compute `num_games` so the assignment runs about 10 to 30 minutes.
5. Create exactly one assignment for that client request.

Compatibility means:

- `threads_per_engine <= client.max_threads`
- `hash_per_engine <= client.max_hash`
- client CPU flags satisfy both engine versions

Game count should be estimated from observed runtime history if available. If not available yet, use a conservative default and learn from completed assignments.

## Refactor order

1. Replace the client startup interface with runtime args and a single `workdir`.
2. Remove checked-in runtime artifacts from `client/`.
3. Replace the current claim API with `jobs/next`.
4. Introduce the new assignment payload.
5. Collapse client capability storage to a simple `cpu_flags` representation.
6. Remove build jobs and pre-split workload generation.
7. Slim engine, version, rating list, and client tables.
8. Rebuild the matchmaker around on-demand assignment sizing.
