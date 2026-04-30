# ResearchPulse

Production-grade multi-agent AI system for monitoring scientific literature, extracting verified claims, and generating living literature reviews with grounded citations.

![Python 3.11](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)
![Celery](https://img.shields.io/badge/Celery-37814A?logo=celery&logoColor=white)
![Redis](https://img.shields.io/badge/Redis-DC382D?logo=redis&logoColor=white)
![ChromaDB](https://img.shields.io/badge/ChromaDB-vector%20search-5B4BFF)
![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white)
![LangSmith](https://img.shields.io/badge/LangSmith-observability-1C3C3C)

## What It Does

Literature reviews take days because the work is not only search. A useful review requires finding relevant papers, reading them, extracting defensible claims, checking that each claim is tied to source text, and synthesizing the results into a coherent document. ResearchPulse automates that full pipeline: search, ingest, embed, extract, verify, synthesize, and store a review that can be refreshed as new papers appear.

The system uses a multi-agent architecture where each agent has one responsibility. `SearchAgent` plans and runs paper discovery. `ExtractAgent` turns retrieved chunks into structured claims. `SynthesisAgent` writes the review only after citations have been verified against ChromaDB metadata. Citations are grounded by `chunk_id` and `paper_id` validation before the final review is saved, so hallucinated source identifiers are rejected in code rather than handled by prompt wording alone.

ResearchPulse is not a RAG chatbot. It runs durable asynchronous jobs through Celery and Redis, stores source chunks in a vector database, validates citation references structurally, streams lifecycle and trace events through Server-Sent Events, and records execution details for operational debugging. The system is built for long-running agent workflows where failures, retries, observability, and traceability matter.

## Architecture

```text
User
  |
  v
Next.js UI / HTTP Client
  |
  v
FastAPI API
  |
  v
Redis Queue
  |
  v
Celery Worker
  |
  v
+------------------------------------------------------------------+
| SearchAgent -> EmbeddingService -> ExtractAgent -> SynthesisAgent |
+------------------------------------------------------------------+
  |
  v
Review + citations + trace
```

| Component | Role |
|---|---|
| FastAPI | HTTP API, request validation, response serialization, and SSE endpoints. It delegates work to services and pipelines. |
| Redis | Broker for Celery jobs and pub/sub transport for real-time lifecycle and trace events. |
| Celery | Executes long-running research pipelines outside the request path. |
| ChromaDB | Stores paper chunks and metadata for semantic retrieval and citation validation. |
| LangSmith | Optional tracing backend for agent and LLM spans. |
| Flower | Operational dashboard for queue depth, workers, retries, and task history. |
| Next.js | Frontend for topic submission, review display, citation inspection, and trace viewing. |

### Agent Responsibilities

`SearchAgent` is responsible for literature discovery. It plans search queries, calls paper search providers, deduplicates candidates, and ranks papers. It must not fetch full text, write reviews, persist database rows, or decide citation validity.

`ExtractAgent` is responsible for converting retrieved paper chunks into structured claims. It receives real chunks from ChromaDB, presents bounded context to the LLM, and maps model output back to known chunk identifiers. It must not invent chunk IDs, search for new papers, synthesize the final review, or write database state.

`SynthesisAgent` is responsible for writing the final literature review from verified claims. It builds citation tokens from claims that have passed `chunk_id` validation and saves only grounded citation metadata. It must not perform paper discovery, mutate vector storage, or trust citation identifiers produced by the LLM without validation.

`Orchestrator` coordinates the pipeline phases. It owns execution order, budget sharing, tracing, lifecycle events, and failure propagation. It must not contain provider-specific tool logic or direct persistence queries.

## Tech Stack

| Area | Technology |
|---|---|
| Backend | Python 3.11, FastAPI, Celery, SQLAlchemy, Pydantic |
| AI | Gemini OpenAI-compatible API via the OpenAI SDK and Instructor for structured output; no LangChain agent runtime |
| Vector DB | ChromaDB with default all-MiniLM-L6-v2-style local embeddings |
| Queue | Redis, Celery, Celery Beat |
| Observability | LangSmith, Flower, structured logging with `structlog`, persisted agent traces |
| Frontend | Next.js 14, TypeScript |
| Infrastructure | Docker Compose |

## Getting Started

### 1. Clone the repository

```bash
git clone https://github.com/<your-org>/researchpulse.git
cd researchpulse
```

### 2. Configure environment

```bash
cp .env.example .env
```

Required variables:

| Variable | Required | Description |
|---|---:|---|
| `LLM_PROVIDER` | Yes | LLM provider. Use `gemini` for the production path or `local` for Ollama. |
| `GEMINI_API_KEY` | Yes when `LLM_PROVIDER=gemini` | Google AI Studio API key used by the primary LLM provider. |
| `LANGCHAIN_API_KEY` | Required for LangSmith tracing | LangSmith API key. Set `LANGCHAIN_TRACING_V2=true` to enable trace export. |
| `LANGCHAIN_TRACING_V2` | No | Enables LangSmith tracing when set to `true`. |
| `LANGCHAIN_PROJECT` | No | LangSmith project name. Defaults to `researchpulse`. |
| `OPENAI_API_KEY` | No | Optional fallback provider after Gemini. |
| `OPENAI_BASE_URL` | No | Optional override for the OpenAI-compatible fallback endpoint. |
| `OPENAI_MODEL` | No | Optional fallback model override. |
| `REDIS_URL` | No | Redis connection URL. Docker Compose sets this to `redis://redis:6379/0`. |
| `CHROMA_HOST` | No | ChromaDB hostname. Docker Compose sets this to `chroma`. |
| `CHROMA_PORT` | No | ChromaDB port. Docker Compose sets this to `8000`. |
| `DATABASE_URL` | No | SQLAlchemy database URL. Docker Compose uses SQLite at `/data/researchpulse.db`. |

### 3. Start the stack

```bash
docker compose up
```

Services:

| Service | URL |
|---|---|
| Frontend | `http://localhost:3000` |
| API | `http://localhost:8000` |
| API docs | `http://localhost:8000/docs` |
| Flower | `http://localhost:5555` |
| ChromaDB | `http://localhost:8001` |

## How To Use

Create a topic and enqueue a research pipeline:

```bash
curl -X POST http://localhost:8000/api/v1/topics \
  -H "Content-Type: application/json" \
  -d '{"name": "retrieval augmented generation"}'
```

The response includes `id` and `job_id`. Use `id` as the topic identifier and `job_id` as the trace identifier.

Retrieve the generated review:

```bash
curl http://localhost:8000/api/v1/reviews/{topic_id}
```

Inspect the persisted agent decision trace:

```bash
curl http://localhost:8000/api/v1/traces/{job_id}
```

Open `http://localhost:5555` for the Flower queue dashboard.

Open `http://localhost:3000` for the frontend.

## Key Engineering Decisions

### Native Provider SDK Instead Of LangChain Agents

ResearchPulse uses direct provider calls through the OpenAI-compatible SDK path and structured output validation rather than a LangChain agent runtime. The goal is direct control over the tool loop, retry behavior, provider fallback, circuit breaking, logging, and failure semantics. Agent abstractions should not hide API errors, malformed tool calls, or provider-specific retry decisions.

The current implementation uses Gemini as the primary production provider. If the project is migrated to Anthropic Claude, the same principle should hold: use native tool calling directly and keep the orchestration loop explicit.

### Citation Grounding Via `chunk_id` Validation

LLMs hallucinate sources. Prompt instructions reduce the frequency but do not create a guarantee. ResearchPulse validates citations structurally by checking that every cited `chunk_id` exists in ChromaDB and belongs to the expected `paper_id`. Claims that cannot be mapped to stored source chunks are rejected before synthesis metadata is persisted.

This moves citation correctness from prompt compliance into application invariants. The model may write prose, but it does not get to define source truth.

### Celery And Redis Instead Of Serverless

Agent runs can take minutes. They involve external API calls, document fetching, vector writes, retries, and synthesis. Serverless platforms with short execution windows, cold starts, and weak long-running stream semantics are a poor fit for this workload. Celery and Redis provide durable queues, explicit retries, worker concurrency, operational visibility through Flower, and a clean separation between HTTP request handling and background execution.

### Two SSE Streams

ResearchPulse separates lifecycle events from trace events. Lifecycle streams report coarse job state such as queued, started, done, and failed. Trace streams report real-time agent steps, tool calls, durations, token counts, and errors. These streams serve different consumers and should not block each other: UI status can remain lightweight while trace viewers receive high-volume debugging data.

## Project Structure

```text
researchpulse/
├── backend/
│   ├── app/
│   │   ├── agents/          Agent orchestration and decision logic.
│   │   ├── api/             FastAPI routers and response models.
│   │   ├── jobs/            Celery task definitions.
│   │   ├── models/          Pydantic schemas and data contracts.
│   │   ├── repositories/    SQLAlchemy persistence access.
│   │   ├── services/        Business logic and workflow actions.
│   │   ├── tools/           Agent-callable tools and tool schemas.
│   │   ├── observability/   Logging, tracing, and cost utilities.
│   │   ├── resilience/      Retry and circuit breaker utilities.
│   │   └── pipelines/       High-level job enqueueing and topic workflow entry points.
│   ├── tests/               Unit and integration tests.
│   ├── main.py              FastAPI application entrypoint.
│   └── celery_worker.py     Celery application and beat schedule.
├── frontend/
│   └── src/app/             Next.js routes for topics, reviews, and traces.
├── docker-compose.yml       Local production-like stack.
└── README.md
```

## Screenshots

<!-- screenshot: frontend review with citation badges -->

<!-- screenshot: LangSmith trace showing agent spans -->

<!-- screenshot: Flower dashboard with active workers -->

<!-- screenshot: real-time trace viewer in the UI -->
