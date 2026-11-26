# DeepLingo

DeepLingo helps learners study a language from real content (YouTube videos with
transcripts) with a companion, Tata: watch, look up and save words, practise and
review them, and speak. The backend owns all pedagogy; the web client presents it.

## Repository

| Path | What it is |
|---|---|
| `backend/` | FastAPI modular monolith, PostgreSQL/Supabase, Celery content worker, AI integration |
| `deeplingo_web/` | React/TypeScript web client (active). The Flutter app was removed; it lives in git history at tag `archive/flutter-app-20261115` |
| `docs/architecture/` | Backend module boundaries, database schema/ERD, diagrams |
| `docs/runbooks/` | Operational procedures (content worker, Supabase, GCP deployment) |
| `docs/product/` | Product requirements (`PRD.md`), current status (`STATUS.md`), privacy notice |

Start with [AGENTS.md](AGENTS.md) (working rules), [PRD](docs/product/PRD.md) (what the product is and where it is going) and [STATUS](docs/product/STATUS.md). The old ADRs,
architecture and product documents were deleted on 2026-10-26; they stay in git history (see STATUS).
The development cloud deployment is described in the [GCP runbook](docs/runbooks/gcp-staging.md).

## Backend at a glance

```
backend/app/
  main.py        bootstrap/ (api.py, worker.py, wiring/)   platform/   kernel/
  modules/{identity,content,learner,learning,review,practice,progress,activity}/
    contracts.py  domain/  application/  infrastructure/  api/  [worker/]
backend/tests/<module>/      backend/scripts/<module>/
```

Boundaries are enforced by `backend/.importlinter` inside the test suite
([module boundaries](docs/architecture/BACKEND_BOUNDARIES.md)).

```bash
cd backend && venv/Scripts/python.exe -m pytest -q
```

Run the API with `uvicorn app.main:app`; run the content worker on Linux with
`celery -A app.bootstrap.worker worker --pool=prefork` (see
[content worker runbook](docs/runbooks/content-worker.md)).
