# ResearchPulse

A multi-agent research monitoring system that tracks arXiv papers on a topic, extracts claims, synthesizes findings with verified citations, and maintains a "living review" that updates as new papers arrive.

## Quick Start

```bash
cp .env.example .env
# Edit .env e adicione GEMINI_API_KEY (obtenha em https://aistudio.google.com/app/apikey)

docker compose up
```

- Frontend: http://localhost:3000
- API: http://localhost:8000
- API docs: http://localhost:8000/docs
- Flower (queue monitor): http://localhost:5555

That's it. No manual DB migrations, no seed data, no extra setup.

---

## Architecture

```
researchpulse/
├── backend/
│   ├── app/
│   │   ├── agents/          # LLM agents with agentic loops
│   │   ├── tools/           # Tool callables + Gemini function declarations
│   │   ├── services/        # Business logic (no HTTP, no DB queries)
│   │   ├── jobs/            # Celery async tasks
│   │   ├── repositories/    # All SQLite queries live here
│   │   ├── models/          # Pydantic models (data shapes)
│   │   ├── pipelines/       # High-level workflow coordinators
│   │   └── api/             # FastAPI route handlers
│   ├── main.py              # FastAPI app entry
│   └── celery_worker.py     # Celery app + beat schedule
└── frontend/
    └── src/app/
        ├── page.tsx                 # Topic list + add topic
        ├── review/[id]/page.tsx     # Living review with citations
        └── traces/[jobId]/page.tsx  # Step-by-step agent trace viewer
```

**Folder responsibilities:**

| Folder | Responsibility |
|---|---|
| `agents/` | Agent classes. Each owns an agentic loop and a set of tools. No DB access. |
| `tools/` | Pure functions callable by agents. Each file has callables + Gemini `types.Tool` / function declarations. |
| `services/` | Business logic. Calls repositories and tools. No HTTP. |
| `jobs/` | Celery task wrappers. Thin — they call services/agents only. |
| `repositories/` | SQLAlchemy queries. One class per table. Returns Pydantic models. |
| `models/` | Pydantic v2 models. Data contracts only — no methods. |
| `pipelines/` | Coordinates multi-step workflows (enqueue jobs, manage topic state). |
| `api/` | FastAPI routers. Validate requests, call services/pipelines, return responses. |

---

## The Agent Loop

```
User adds topic "RAG for scientific papers"
          │
          ▼
   POST /api/v1/topics
          │
          ▼
  ResearchPipeline.start()
          │   enqueues
          ▼
   run_pipeline_job (Celery)
          │
          ▼
   Orchestrator.run()
    │
    ├─► SearchAgent
    │       │
    │       ▼
    │   ┌─────────────────────────────────────────┐
    │   │           AGENTIC LOOP                  │
    │   │  messages = [{role: user, content: …}]  │
    │   │  while True:                            │
    │   │    response = client.models.generate_content()  │
    │   │    if no function_call parts: break           │
    │   │    if function_call parts:                    │
    │   │      results = dispatch_tools()         │
    │   │      messages.append(assistant+results) │
    │   └─────────────────────────────────────────┘
    │       │ returns list[Paper]
    │
    ├─► PaperService.ingest() × N papers
    │       │  fetch full text (ar5iv / abstract)
    │       │  chunk text into 512-token windows
    │       │  store chunks in ChromaDB
    │
    ├─► ExtractAgent × N papers
    │       │  semantic_search(paper_id=…)
    │       │  extract_claims(chunk_id=…)
    │       │ returns list[Claim]
    │
    ├─► SynthesisAgent
    │       │  verify_citation(chunk_id, paper_id) × M claims
    │       │  writes synthesis with [chunk_id] markers
    │       │  rejects any unverified claims
    │       │ returns synthesis + cited_papers
    │
    └─► ReviewService.save()  →  DB  →  UI
```

---

## Citation Grounding

The system enforces that the synthesis can **only cite text that was actually retrieved and stored**.

1. `EmbeddingService` chunks each paper and stores chunks in ChromaDB with a deterministic `chunk_id` = `{paper_id}::chunk::{index}`.
2. `ExtractAgent` calls `semantic_search(paper_ids=[paper.id])` — it receives real `chunk_id` values back.
3. `SynthesisAgent` calls `verify_citation(chunk_id, paper_id)` for **every** claim before citing it. This function:
   - Checks ChromaDB: does this `chunk_id` exist?
   - Checks the stored `paper_id` metadata matches the claimed paper.
   - Returns `verified=False` for hallucinated chunk IDs.
4. Claims with `verified=False` are excluded from the synthesis. The count of rejected citations is stored in the `Trace` and shown in the UI.
5. Inline citation markers in the synthesis text (`[chunk_id]`) are rendered as clickable arXiv links in the frontend — clicking one opens the source paper.

This makes it **structurally impossible** for the synthesis to contain a citation not grounded in retrieved text.

---

## Adding a New Tool to an Agent

1. **Write the callable** in `app/tools/your_tools.py`:
   ```python
   def my_tool(param: str) -> dict:
       result = do_something(param)
       return {"result": result}
   ```

2. **Declare the tool for Gemini** (`types.FunctionDeclaration` / `types.Tool`) in the same file — see existing tools under `app/tools/` for patterns.

3. **Register it in the agent** that should use it:
   ```python
   class MyAgent(BaseAgent):
       def __init__(self, job_id):
           super().__init__(job_id)
           self.tools = [my_tool_schema]          # Gemini tool declaration
           self.tool_map = {**MY_TOOL_MAP}         # Python callable
   ```

`BaseAgent._dispatch_tools()` handles the rest — it routes tool calls, retries on failure, and records every execution to the trace.

---

## Celery Queues & Flower

**Queue topology:**

| Task | When | Retry |
|---|---|---|
| `jobs.run_pipeline` | On topic creation | 1× after 60s |
| `jobs.process_paper` | Per paper during pipeline | 3× with backoff |
| `jobs.refresh_reviews` | Every hour (Beat) | None |

**Flower** (http://localhost:5555) shows you in real time:
- Active tasks and which worker is running them
- Task history with success/failure status
- Retry counts per task
- Queue depth (how many jobs are waiting)
- Worker resource usage

If a pipeline gets stuck, Flower lets you inspect which Celery task is blocked and revoke it if needed.

**Beat scheduler** runs `refresh_reviews` on the `:00` of every hour. It checks arXiv for papers newer than `last_fetched_at` per topic, and re-enqueues `run_pipeline` only when new papers exist. This is how the "living review" stays current without manual intervention.

---

## Stack

| Component | Technology |
|---|---|
| Backend API | FastAPI + uvicorn |
| LLM | Gemini 2.0 Flash (Google Gemini API, native function calling) |
| Queue | Redis 7 + Celery 5 |
| Queue monitor | Flower |
| Vector DB | ChromaDB (local, cosine similarity) |
| Relational DB | SQLite (via SQLAlchemy) |
| Frontend | Next.js 14 + TypeScript |
| Package manager | uv (Python), npm (Node) |
| Infrastructure | Docker Compose |
