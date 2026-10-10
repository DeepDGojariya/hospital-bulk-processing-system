# Hospital Bulk Processing API

A service that accepts a CSV of hospitals and creates them in the
[Hospital Directory API](https://hospital-directory.onrender.com/docs) as one
batch. The batch is activated only when every hospital was created.

Live URL: _added after deployment_ (interactive docs at `/docs`)

## Features

- `POST /hospitals/bulk`: upload a CSV, get per-row results (required task)
- A web page at `/` to validate a CSV, upload it, watch live progress, and
  resume a failed batch
- Concurrent upstream calls with a bounded, shared concurrency limit
- Retries with exponential backoff and jitter for transient upstream failures
- Progress tracking by polling or WebSocket
- Resume for failed batches, with reconciliation against the upstream to avoid
  creating a hospital twice
- CSV validation endpoint
- Test suite that runs without network access
- Dockerfile, docker-compose, and Render blueprint

## Quick start

```bash
# Local (requires uv: https://docs.astral.sh/uv/)
uv sync
uv run uvicorn app.main:app --reload

# Docker
docker compose up --build
```

The upload page is then at http://localhost:8000 and the API docs at
http://localhost:8000/docs.

```bash
curl -F file=@samples/hospitals.csv http://localhost:8000/hospitals/bulk
```

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| POST | `/hospitals/bulk` | Process a CSV. `?mode=sync` (default) or `?mode=async` |
| POST | `/hospitals/bulk/validate` | Validate a CSV without calling the upstream |
| GET | `/hospitals/bulk/{batch_id}` | Batch status and progress |
| WS | `/hospitals/bulk/{batch_id}/ws` | Live progress snapshots |
| POST | `/hospitals/bulk/{batch_id}/resume` | Retry the failed part of a batch |
| GET | `/health` | Health check |
| GET | `/` | Upload page (static files under `/static`) |

### CSV format

```csv
name,address,phone
General Hospital,123 Main St,555-1234
City Medical Center,45 Oak Avenue,
```

- `name` and `address` are required; `phone` is optional (the column may be omitted).
- At most 20 hospitals per file. UTF-8, with or without a BOM.
- Header names are case-insensitive. Unknown columns are rejected; trailing
  empty columns, which spreadsheets often export, are ignored.
- `row` in results and errors is the 1-based number of the data row. The
  header and blank lines are not counted.
- An invalid file is rejected as a whole with `422` and every error listed;
  nothing is sent to the upstream.

### Response

```json
{
  "batch_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "completed",
  "total_hospitals": 2,
  "processed_hospitals": 2,
  "failed_hospitals": 0,
  "processing_time_seconds": 0.412,
  "batch_activated": true,
  "activation_error": null,
  "hospitals": [
    {"row": 1, "hospital_id": 101, "name": "General Hospital", "status": "created_and_activated", "error": null},
    {"row": 2, "hospital_id": 102, "name": "City Medical Center", "status": "created_and_activated", "error": null}
  ]
}
```

`status`, `activation_error`, and the per-row `error` are additions to the
response in the assignment. Batch `status` is `processing`, `completed`, or
`failed`. Row `status` is `pending`, `created`, `created_and_activated`, or
`failed`.

### Status codes

| Code | Meaning |
|---|---|
| 200 | Processing ran. Check `status`: a batch with failed rows is still `200` because it exists and can be resumed |
| 202 | Accepted in `mode=async`; poll the `Location` header |
| 400 | Request body is not valid multipart form data |
| 404 | Unknown batch |
| 409 | Resume requested for a batch that is processing or completed |
| 413 | Upload larger than `MAX_UPLOAD_BYTES`; oversized bodies are cut off while they arrive, not after |
| 422 | Invalid CSV or request. The body is always `{"detail": "...", "errors": [{"row", "field", "message"}]}` |
| 502 | Resume could not read the batch from the upstream |

### Progress tracking and resume

```bash
# Start in the background, then poll
curl -i -F file=@samples/hospitals.csv "http://localhost:8000/hospitals/bulk?mode=async"
curl http://localhost:8000/hospitals/bulk/<batch_id>

# Or stream snapshots (requires websocat)
websocat ws://localhost:8000/hospitals/bulk/<batch_id>/ws

# Retry a failed batch
curl -X POST http://localhost:8000/hospitals/bulk/<batch_id>/resume
```

## Architecture

```
app/
  main.py                     application factory, lifespan-managed HTTP client
  config.py                   environment-driven settings
  schemas.py                  API models and status enums
  api/                        routes only: translate HTTP to service calls
  services/csv_parser.py      pure function: bytes -> rows or errors
  services/processor.py       orchestrates run and resume
  clients/hospital_directory.py   upstream calls and retry policy
  store/                      BatchStore interface + in-memory implementation
  static/                     upload page: plain HTML, CSS, and JavaScript
```

Request flow for `POST /hospitals/bulk`:

1. A middleware rejects oversized bodies as they arrive; the route reads the
   upload and calls the CSV parser.
2. The processor creates a batch with a new UUID and stores it, then pings the
   upstream to make sure it is awake.
3. Rows are sent to the upstream concurrently through one pooled
   `httpx.AsyncClient`, bounded by a semaphore.
4. Each finished row updates the store, which publishes a snapshot to
   WebSocket subscribers.
5. If every row was created, the batch is activated.

Each layer depends only on the one below it through a small interface, so the
parser, client, store, and processor are tested in isolation.

## Upload page

The page at `/` is a thin client over the public API and uses nothing else:

- **Validate** calls `/hospitals/bulk/validate` and lists errors by row and field.
- **Upload and process** starts the batch with `mode=async`, then follows it
  over the WebSocket, updating the progress bar and the per-row table. If the
  socket cannot connect or drops, it polls the status endpoint instead.
- **Resume failed batch** appears when a batch ends `failed`.

It is plain HTML, CSS, and JavaScript with no build step, so it ships in the
same container. Values from the CSV and the API are written to the page as
text, never as HTML.

## Design decisions

**FastAPI over Flask.** The work is I/O bound: up to 20 HTTP calls per upload.
FastAPI's async model lets those calls run concurrently on one event loop
without threads, and WebSocket support and OpenAPI docs come built in.

**Synchronous by default, asynchronous on request.** The default call returns
the full result, as the assignment specifies. `?mode=async` returns `202`
immediately, which is what makes progress tracking meaningful. Both modes run
the same code path.

**Validate everything before creating anything.** A CSV with any invalid row
is rejected before the first upstream call, so bad input never leaves a
half-created batch behind.

**Partial failure keeps the batch, inactive.** If a row fails, the hospitals
already created stay in the batch, the batch is not activated, and the caller
can resume. Hospitals created with a batch ID are inactive upstream, so a
failed batch is never visible as live data.

**Retries are limited to failures that are safe to retry.** Connection errors
and `429/502/503/504` are retried up to three attempts with exponential backoff and
jitter, waiting at least as long as a `Retry-After` header asks (capped at 30
seconds). A read timeout on a create is not retried, because the upstream may
have stored the hospital and a retry would duplicate it.

**Resume reconciles first.** Before retrying, resume lists the batch upstream
and adopts any hospital that exists there but was recorded locally as failed.
Combined with the retry rule above, a create that timed out but did reach the
upstream is not created a second time. Rows are matched on name, address, and
phone. See Limitations for the cases this cannot cover.

**Wake the upstream before creating.** The upstream runs on a free instance
that can take longer than the request timeout to cold-start. Since a timed-out
create cannot be retried safely, each run first sends a harmless request that
can be retried. If the upstream stays unreachable, every row is marked failed
without a single create being sent, and the batch can be resumed later.

**One concurrency limit for the whole service.** The limit lives in the
upstream client and is shared by all batches, so many simultaneous uploads
cannot multiply the load on the upstream API. A slot is held for one attempt
only, so a call that is backing off does not block the others.

**A bug in one row does not lose the batch.** An unexpected error while
creating a row is logged with its traceback and recorded on that row; the
caller still receives the batch ID and can resume.

**Failures are logged.** Row failures, retries, failed activations, and
hospitals adopted during reconciliation are logged with the batch ID, and each
run logs a one-line summary.

## Performance

Each create call to the upstream takes about 5 seconds, so the number of
round trips made one after another decides the total time. Rows are sent
concurrently, which makes the total roughly `ceil(rows / limit)` round trips
instead of `rows`.

Measured against the live upstream (activation included):

| Upload | Concurrency limit | Time |
|---|---|---|
| 1 hospital | any | 5.6 s |
| 20 hospitals | 10 | 11.8 s |
| 20 hospitals | 20 (default) | 7.0 s |

These are single runs, not averages. The first two rows were measured before
the warm-up request was added, which costs well under a second per batch.

Sending 20 hospitals one at a time would take about 20 x 5.6 s, close to two
minutes; that figure is calculated from the single-row time, not measured.
The default limit equals the maximum file size, so a full file goes out in
one wave. Connections are pooled and reused across rows and batches. The
first request after the upstream has been idle can be slower, because its
free Render instance cold-starts.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `HOSPITAL_API_BASE_URL` | `https://hospital-directory.onrender.com` | Upstream API |
| `MAX_CSV_ROWS` | `20` | Maximum hospitals per file |
| `MAX_UPLOAD_BYTES` | `1048576` | Maximum upload size |
| `MAX_CONCURRENCY` | `20` | Concurrent upstream calls, service-wide |
| `REQUEST_TIMEOUT_SECONDS` | `30` | Per-request upstream timeout |
| `MAX_RETRIES` | `3` | Attempts per upstream call |
| `RETRY_BACKOFF_SECONDS` | `0.5` | Base backoff |
| `MAX_STORED_BATCHES` | `500` | Batches kept in memory |

## Testing

```bash
uv run pytest
uv run ruff check . && uv run ruff format --check .
```

The upstream is replaced by a stateful in-process fake
(`tests/fakes.py`) plugged into httpx as a transport, so the tests exercise
the real client, retry, and concurrency code without network access. Coverage
includes CSV edge cases, retry rules, partial failure, activation failure,
resume and reconciliation, concurrency limits, every endpoint's error codes,
and the WebSocket stream.

## Deployment

The repository contains a Render blueprint (`render.yaml`) that builds the
Dockerfile and uses `/health` as the health check. In Render: New > Blueprint,
select this repository, and apply.

## Limitations and how this would scale

- **State is in memory.** Batches are lost on restart and are not shared
  between processes, so the service runs as a single worker. `BatchStore` is
  an interface; a Redis implementation (hash per batch, pub/sub for progress)
  would allow several workers and survive restarts.
- **Background runs live in the web process.** A restart during a
  `mode=async` run abandons it. A task queue (Celery, arq) with the persistent
  store would make runs durable; resume already handles picking up a
  half-finished batch.
- **The store keeps the last 500 batches**, evicting the oldest finished one.
- **A duplicate is still possible in two cases,** because the upstream API has
  no idempotency key. First, a proxy returns `502/503/504` after the upstream
  already stored the hospital, and the retry creates it again. Second, resume
  is called while a timed-out create is still being committed upstream, so the
  reconciliation listing does not show it yet.
- **No authentication**, as the assignment does not ask for it.
