# Content worker runtime

Owner decision2026-10-01: **SUPPORTED CONTENT WORKER: Linux + Celery prefork**.
Model: async reliability.
**Windows-native thread pool: UNQUALIFIED DEVELOPMENT CONVENIENCE / NOT RELIABILITY QUALIFIED.**
Windows remains usable for API development/unit tests. Do not restore threads/solo
as a second production-supported topology or claim that configured limits work there.

## Canonical startup

Working directory: backend root; use the backend Linux environment/dependencies.
No hosted topology rollout is authorized by this document.

```bash
python -m scripts.content.run_content_worker
# Equivalent explicit invocation:
celery -A app.bootstrap.worker:celery_app worker --pool=prefork --concurrency=2 --prefetch-multiplier=1 --queues=celery --loglevel=INFO
# Separate process, not embedded worker Beat:
celery -A app.bootstrap.worker:celery_app beat --loglevel=INFO
```

The launcher rejects non-Linux. Production soft1500/hard1800 and lease2100 remain
in existing task/config sources; no duplicate CLI deadline defaults. Concurrency2,
prefetch multiplier1, single celery queue, early ACK unchanged. PostgreSQL owns
intent/retry/claim fencing/CAS. Redis is transport, not recovery authority.
Celery/billiard parent supervises hard-killed child replacement; an external service
supervisor for parent/Beat crash remains deployment operations work, not implemented
by this task. Local proof must show the parent survives repeated child kills.

## Resource inventory / lifecycle boundary

| Resource reachable by active Content tasks | Classification | Ownership / correction |
| --- | --- | --- |
| Settings, Celery task definitions, JSON DTO/type constants | SAFE PRE-FORK | Configuration/registrations, no authoritative in-memory learner state |
| Supabase anon/service wrappers and imported aliases | STATELESS / IMMATERIAL at import; concrete client POST-FORK REQUIRED | PID cache + stable proxy; factory not called at import; child resets inherited ownership/mutex |
| Supabase auth/session and PostgREST HTTP connection pools | POST-FORK REQUIRED | Real SDK created on first child use; repositories created per task; child reuses PID-owned client |
| Concrete schema/request builders returned by SDK | POST-FORK REQUIRED | Obtained within task/repository operation; never global cached service/repository |
| Repositories, claim adapters, Content factories | STATELESS / IMMATERIAL before task | Factory constructs claim-scoped repositories/services inside task using current client proxy |
| OpenAI-compatible extraction/enrichment clients/httpx | POST-FORK REQUIRED | Factories instantiate per task, not module scope; unchanged strict schemas/provider ports/timeout policy; normal vendor object lifecycle/process teardown |
| YouTubeService/source wrapper | STATELESS / IMMATERIAL | Constructed per task; requests/vendor fetch invoked only during execution; no module-owned connected HTTP client |
| Transcript normalizer / language/reference dictionaries | SAFE PRE-FORK | Pure/read-only data; per-call mutation local |
| Optional Cutlet/native tokenizer | POST-FORK REQUIRED | Previously created at import; now PID-owned lazy engine; no unrelated tokenizer/toolchain installation |
| Optional pypinyin module tables / pure romanization metadata | SAFE PRE-FORK | No live network/socket/session; existing optional capability unchanged |
| Celery/Kombu Redis producer pools | POST-FORK REQUIRED by vendor lifecycle | Celery manages process pool/connection cleanup; bounded explicit producer connection inside task; no manually shared Redis instance in active worker |
| Application cache mutex | POST-FORK REQUIRED | register_at_fork replaces inherited lock; PID transition also resets; mutex held at parent fork covered by real Linux test |
| Event loops / thread-local harness clients | STATELESS / IMMATERIAL to active V3 production | Active V3 synchronous, no global event loop or thread-local requirement. Old proof thread-local patches are not active V3 runtime design |

`ProcessClientProxy` preserves existing import names but is not a `None` sentinel:
unconfigured operations fail closed with a safe configuration error; bool/is_connected
resolve availability. No SQL/service-role credentials reach clients/logs.
No module-global repository/service was found capturing a concrete pre-fork network
client in the active task factories. Holding a concrete SDK request across fork is
not supported; factories must remain inside tasks. Child shutdown closes already
initialized Supabase PostgREST/auth resources; SIGKILL relies on OS teardown.
The process client cache lives in `app/platform/process_clients.py`.
