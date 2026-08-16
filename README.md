# Harmony Bot v2.1

**Harmony Bot** is a conversational assistant for medical and mental-health
questions. It routes each question to a domain, retrieves genuinely similar
examples from two Hugging Face datasets, and answers with a Llama-3.1 model
served through the Hugging Face Inference API — streamed token by token,
sanitised before it ever touches the DOM.

<sub>FastAPI · Starlette SSE · scikit-learn TF-IDF · Hugging Face Inference Providers · vanilla ES modules · Docker · GitHub Actions</sub>

---

## Contents

- [Features](#features)
- [Architecture](#architecture)
  - [System overview](#system-overview)
  - [Request lifecycle](#request-lifecycle-chatstream)
  - [Index build](#index-build)
  - [Routing and retrieval](#routing-and-retrieval)
  - [Model resilience](#model-resilience)
  - [Trust boundary](#trust-boundary)
  - [Build and deployment](#build-and-deployment)
- [Project structure](#project-structure)
- [Installation](#installation)
- [Configuration](#configuration)
- [API](#api)
- [Observability](#observability)
- [Tests](#tests)
- [Docker](#docker)
- [Limitations](#limitations)
- [What's upgradable](#whats-upgradable)

---

## Features

- **Retrieval-grounded answers** — TF-IDF nearest-neighbour search over ~23k
  real patient/counsellor exchanges, so the injected context actually relates
  to the question.
- **Live token streaming** — replies render as they are generated over SSE.
- **Conversation memory** — a rolling window of recent turns, per session,
  with client-supplied history taking precedence so a restored chat survives a
  server restart.
- **Model failover** — a ranked list of models with sticky failover, retries
  with jittered backoff, and permanent-vs-transient error classification.
- **Crisis safeguards** — deterministic detection of self-harm language, with
  helpline resources surfaced before the model is even called.
- **Sanitised output** — model Markdown is escaped and whitelisted before it
  reaches the DOM, and the page ships a strict CSP.
- **Rate limited** — in-process sliding window on the generation endpoints, so
  one visitor cannot drain the inference quota.
- **Structured logging** — every line carries a request id; JSON in production.
- **Graceful degradation** — if the datasets cannot be fetched, the app still
  boots and answers without retrieval.

### Interface

- **Saved conversations** — grouped by recency, searchable, renameable by first
  message, exportable as Markdown. Stored only in your browser.
- **Resumable context** — a conversation restored after a refresh replays its
  recent turns, so the model keeps its memory even across a server restart.
- **Regenerate** any reply, **stop** mid-generation, **copy** any message.
- **Reader-friendly scrolling** — the view follows new tokens only while you
  are already at the bottom, never yanking the page mid-read.
- **Light / dark / system** theme, applied before first paint.
- **Keyboard-first** — <kbd>Ctrl</kbd>+<kbd>K</kbd> search,
  <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>O</kbd> new chat,
  <kbd>Esc</kbd> stop, <kbd>?</kbd> for the full list.
- **Accessible** — skip link, ARIA live regions, visible focus rings, native
  `<dialog>` focus trapping, `prefers-reduced-motion` support.
- **No image or font payload** — the entire UI is CSS and inline SVG.

## Demo

[Harmony Bot on Hugging Face Spaces](https://huggingface.co/spaces/Shabi23/HarmonyBot)

---

## Architecture

Four ideas shape the whole system:

1. **One pipeline, two transports.** `ChatService` owns
   *route → retrieve → prompt → generate → render*. The streaming and
   non-streaming endpoints are two thin adapters over the same code, so they
   can never drift.
2. **The server is effectively stateless.** Conversations live in the browser.
   The in-process `SessionStore` is a convenience for API clients, not the
   source of truth — a client that sends its own `history` wins.
3. **Failure degrades, it does not cascade.** A dead dataset costs retrieval
   quality; a retired model costs a failover hop; a broken stream costs one
   reply. None of them cost availability.
4. **Model output is untrusted input.** It is escaped, allowlisted and
   linkified on the server before the browser is allowed to treat it as markup.

### System overview

```mermaid
%%{init: {"theme":"base","themeVariables":{"fontSize":"13px","primaryColor":"#161b22","mainBkg":"#161b22","primaryTextColor":"#e6edf3","secondaryTextColor":"#e6edf3","tertiaryTextColor":"#e6edf3","primaryBorderColor":"#30363d","lineColor":"#8b949e","textColor":"#e6edf3","titleColor":"#e6edf3","nodeTextColor":"#e6edf3","clusterBkg":"#0d1117","clusterBorder":"#30363d","edgeLabelBackground":"#161b22"}}}%%
flowchart TB
    subgraph CLIENT["BROWSER · zero-dependency ES modules"]
        direction TB
        HTML["templates/index.html<br/>chat shell · dialogs · ARIA live regions"]
        APPJS["app.js<br/>orchestration · theme · shortcuts · rendering"]
        APIJS["api.js<br/>fetch + hand-rolled SSE frame parser"]
        STOREJS["store.js<br/>conversations · titles · per-chat session id"]
        UIJS["ui.js<br/>toasts · dialogs · icons · relative time"]
        LS[("localStorage<br/>hb-conversations · 50 max")]
    end

    subgraph EDGE["ASGI EDGE · uvicorn + Starlette middleware, outermost first"]
        direction LR
        MW1["RequestContextMiddleware<br/>request id · access log · X-Request-ID"]
        MW2["SecurityHeadersMiddleware<br/>CSP · nosniff · frame-ancestors none"]
        MW3["RateLimitMiddleware<br/>sliding window on the generation routes"]
        MW4["CORSMiddleware<br/>mounted only when CORS_ORIGINS is set"]
    end

    subgraph ROUTES["ROUTERS · app/routers"]
        direction LR
        PAGES["pages.py<br/>GET / · GET /health"]
        CHATR["chat.py<br/>POST /chat · /chat/stream · /chat/reset"]
        SCHEMAS["schemas.py<br/>pydantic models — malformed input is 422, not 500"]
    end

    subgraph CORE["DOMAIN SERVICES · app/services"]
        direction TB
        CHATS["chat.py — ChatService<br/>route → retrieve → prompt → generate → render"]
        SAFETY["safety.py<br/>deterministic crisis regex, runs before the model"]
        KB["retrieval.py — KnowledgeBase<br/>keyword routing + TF-IDF nearest neighbour"]
        PROMPTS["prompts.py<br/>system persona + references + history assembly"]
        LLM["llm.py — LLMClient<br/>async HF client · retries · sticky failover"]
        REND["rendering.py<br/>markdown2 escape → bleach allowlist → linkify"]
        SESS["sessions.py — SessionStore<br/>in-process, thread-safe, LRU + TTL"]
    end

    subgraph SUPPORT["CROSS-CUTTING"]
        direction TB
        CFG["config.py — Settings<br/>pydantic-settings, env or .env, lru_cached"]
        OBS["observability.py<br/>ContextVar request id · JSON / text formatters"]
    end

    subgraph EXT["EXTERNAL"]
        direction TB
        HFAPI["HF Inference Providers<br/>Llama-3.1-8B → Qwen2.5-7B → Llama-3.3-70B"]
        DATA[("HF Datasets<br/>avaliev/chat_doctor<br/>Amod/mental_health_counseling_conversations")]
    end

    HTML --> APPJS
    APPJS --> UIJS
    APPJS --> STOREJS
    APPJS --> APIJS
    STOREJS <--> LS
    APIJS -->|"POST JSON · SSE response"| MW1

    MW1 --> MW2 --> MW3 --> MW4
    MW4 --> PAGES
    MW4 --> CHATR
    CHATR -.->|validates| SCHEMAS

    PAGES -->|"readiness snapshot"| KB
    CHATR --> CHATS

    CHATS --> SAFETY
    CHATS --> KB
    CHATS --> PROMPTS
    CHATS --> LLM
    CHATS --> REND
    CHATS <-->|"fallback when no client history"| SESS

    KB -->|"loaded once at startup, off the event loop"| DATA
    LLM -->|"streaming chat completions"| HFAPI

    CFG -.-> EDGE
    CFG -.-> CORE
    OBS -.-> MW1

    classDef client fill:#0b1f3a,stroke:#2f81f7,color:#cfe3ff,stroke-width:1px
    classDef edge fill:#2a1f05,stroke:#d29922,color:#f7e3ad,stroke-width:1px
    classDef route fill:#1d1233,stroke:#a371f7,color:#e4d5ff,stroke-width:1px
    classDef core fill:#04261c,stroke:#3fb950,color:#c8f2d5,stroke-width:1px
    classDef support fill:#161b22,stroke:#6e7681,color:#c9d1d9,stroke-width:1px
    classDef ext fill:#2d0f1a,stroke:#f778ba,color:#ffd3e6,stroke-width:1px

    class HTML,APPJS,APIJS,STOREJS,UIJS,LS client
    class MW1,MW2,MW3,MW4 edge
    class PAGES,CHATR,SCHEMAS route
    class CHATS,SAFETY,KB,PROMPTS,LLM,REND,SESS core
    class CFG,OBS support
    class HFAPI,DATA ext

    style CLIENT fill:#0d1117,stroke:#2f81f7,color:#79c0ff
    style EDGE fill:#0d1117,stroke:#d29922,color:#e3b341
    style ROUTES fill:#0d1117,stroke:#a371f7,color:#c297ff
    style CORE fill:#0d1117,stroke:#3fb950,color:#56d364
    style SUPPORT fill:#0d1117,stroke:#6e7681,color:#adbac7
    style EXT fill:#0d1117,stroke:#f778ba,color:#ff9bce

    linkStyle default stroke:#8b949e,stroke-width:1.4px
```

### Request lifecycle (`/chat/stream`)

The interesting property here is *ordering*: the domain is announced before
generation, crisis resources are emitted before the first token, and the
sanitised HTML arrives last and replaces everything the browser painted.

```mermaid
%%{init: {"theme":"base","themeVariables":{"fontSize":"13px","primaryColor":"#161b22","primaryTextColor":"#e6edf3","primaryBorderColor":"#30363d","lineColor":"#7a828c","textColor":"#7a828c","actorBkg":"#161b22","actorBorder":"#3fb950","actorTextColor":"#e6edf3","actorLineColor":"#7a828c","signalColor":"#7a828c","signalTextColor":"#7a828c","labelBoxBkg":"#1d1233","labelBoxBorderColor":"#a371f7","labelTextColor":"#e4d5ff","loopTextColor":"#7a828c","noteBkgColor":"#2a1f05","noteBorderColor":"#d29922","noteTextColor":"#f7e3ad","sequenceNumberColor":"#e6edf3","altSectionBkgColor":"#161b22"}}}%%
sequenceDiagram
    autonumber
    participant U as Browser<br/>app.js + api.js
    participant M as Middleware<br/>stack
    participant R as chat.py<br/>router
    participant S as ChatService
    participant K as KnowledgeBase
    participant Z as SessionStore
    participant L as LLMClient
    participant H as HF Inference

    U->>M: POST /chat/stream<br/>{message, session_id, history}
    M->>M: assign request id · check CSP · sliding-window quota
    alt over the rate limit
        M-->>U: 429 + Retry-After
    end
    M->>R: validated ChatRequest
    R->>S: stream(message, session_id, history)

    S->>K: route(message)
    K-->>S: Domain — medical / mental_health / general
    S->>K: retrieve(message, domain)
    K-->>S: top-k Examples above MIN_SIMILARITY
    opt no client history supplied
        S->>Z: history(session_id)
        Z-->>S: last MAX_HISTORY_TURNS turns
    end
    S->>S: build_messages — system persona + references + history + question

    S-->>U: event: meta — the routed domain
    alt crisis language detected
        S-->>U: event: crisis — helplines, rendered before generation
    end

    S->>L: stream(messages)
    L->>H: chat_completion(stream=True)
    loop every delta
        H-->>L: token
        L-->>S: delta
        S-->>U: event: delta — painted as plain text
    end

    opt no client history supplied
        S->>Z: append(user, assistant)
    end
    S-->>U: event: done — sanitised HTML replaces the plain text
    Note over U,H: On LLMError the router emits event: error instead —<br/>generic copy for the user, full detail in the server log.
```

### Index build

Both corpora are pulled and indexed once, on a worker thread, so startup never
blocks the event loop and a network failure costs quality rather than uptime.

```mermaid
%%{init: {"theme":"base","themeVariables":{"fontSize":"13px","primaryColor":"#161b22","mainBkg":"#161b22","primaryTextColor":"#e6edf3","tertiaryTextColor":"#e6edf3","primaryBorderColor":"#30363d","lineColor":"#8b949e","textColor":"#e6edf3","titleColor":"#e6edf3","clusterBkg":"#0d1117","clusterBorder":"#30363d","edgeLabelBackground":"#161b22"}}}%%
flowchart LR
    D1["load_dataset<br/>avaliev/chat_doctor<br/>input → question · output → answer"]
    D2["load_dataset<br/>Amod/counseling<br/>Context → question · Response → answer"]
    CAP["cap each corpus at<br/>MAX_INDEX_ROWS"]
    FILT["drop rows under 40 chars<br/>and boilerplate turns —<br/>'may I answer your health queries'"]
    VEC["TfidfVectorizer<br/>english stopwords · 1-2 grams<br/>50k features · sublinear tf<br/>rows L2-normalised"]
    IDX[("two in-memory indexes<br/>keyed by Domain<br/>ready = True")]

    D1 --> CAP
    D2 --> CAP
    CAP --> FILT --> VEC --> IDX

    FAIL["either download fails"] -.->|"logged, never raised"| DEGRADE["ready = False<br/>app boots and answers<br/>without retrieval"]

    classDef boot fill:#0b1f3a,stroke:#2f81f7,color:#cfe3ff,stroke-width:1px
    classDef bad fill:#2d0f1a,stroke:#f778ba,color:#ffd3e6,stroke-width:1px

    class D1,D2,CAP,FILT,VEC,IDX boot
    class FAIL,DEGRADE bad

    linkStyle default stroke:#8b949e,stroke-width:1.4px
```

### Routing and retrieval

v1 always injected `train[0]`, so every medical question was answered against
the same appendectomy case. This runs per request instead.

```mermaid
%%{init: {"theme":"base","themeVariables":{"fontSize":"13px","primaryColor":"#161b22","mainBkg":"#161b22","primaryTextColor":"#e6edf3","tertiaryTextColor":"#e6edf3","primaryBorderColor":"#30363d","lineColor":"#8b949e","textColor":"#e6edf3","titleColor":"#e6edf3","clusterBkg":"#0d1117","clusterBorder":"#30363d","edgeLabelBackground":"#161b22"}}}%%
flowchart TB
    Q(["user message"]) --> KWV["count keyword hits in<br/>both domain vocabularies"]
    KWV --> ANY{"any keyword<br/>matched?"}
    ANY -->|yes| WIN["higher count wins<br/>ties go to mental health"]
    ANY -->|no| SIM["probe every index<br/>top-1 similarity"]
    SIM --> THR{"best score<br/>≥ 0.25?"}
    THR -->|yes| WIN
    THR -->|no| GEN["Domain.GENERAL<br/>no examples injected"]

    WIN --> SEARCH["cosine search on the routed index<br/>argpartition top-k, no full sort"]
    SEARCH --> FLOOR{"score ≥<br/>MIN_SIMILARITY?"}
    FLOOR -->|yes| KEEP["Example — question, answer, score<br/>truncated to 600 chars each"]
    FLOOR -->|no| DROP["discarded — a weak match is a<br/>misleading exemplar, not a free one"]

    KEEP --> SYS["system message<br/>persona + ground rules + labelled references"]
    GEN --> SYS
    DROP --> SYS
    SYS --> OUT(["messages[] for the model"])

    classDef step fill:#04261c,stroke:#3fb950,color:#c8f2d5,stroke-width:1px
    classDef decision fill:#2a1f05,stroke:#d29922,color:#f7e3ad,stroke-width:1px
    classDef term fill:#1d1233,stroke:#a371f7,color:#e4d5ff,stroke-width:1px
    classDef bad fill:#2d0f1a,stroke:#f778ba,color:#ffd3e6,stroke-width:1px

    class KWV,WIN,SIM,SEARCH,KEEP,SYS step
    class ANY,THR,FLOOR decision
    class Q,OUT,GEN term
    class DROP bad

    linkStyle default stroke:#8b949e,stroke-width:1.4px
```

### Model resilience

v1 pinned a single model id. When `Meta-Llama-3-8B-Instruct` left the Inference
Providers catalogue, every request returned `model_not_supported` and the
product was simply dead. `LLMClient` is built so that cannot happen again.

```mermaid
%%{init: {"theme":"base","themeVariables":{"fontSize":"13px","primaryColor":"#161b22","mainBkg":"#161b22","primaryTextColor":"#e6edf3","tertiaryTextColor":"#e6edf3","primaryBorderColor":"#30363d","lineColor":"#8b949e","textColor":"#e6edf3","titleColor":"#e6edf3","clusterBkg":"#0d1117","clusterBorder":"#30363d","edgeLabelBackground":"#161b22"}}}%%
flowchart TB
    START(["stream(messages)"]) --> PICK["start at the active model index<br/>sticky — a past failover is remembered"]
    PICK --> CALL["AsyncInferenceClient.chat_completion<br/>stream=True"]
    CALL --> RES{"outcome?"}

    RES -->|"tokens flowing"| FIRST{"is this the<br/>first token?"}
    FIRST -->|"yes, and the index moved"| PROMOTE["promote this model to active<br/>every later request skips the dead one"]
    FIRST -->|no| EMIT["yield each non-null delta<br/>the null delta on the terminating chunk is skipped"]
    PROMOTE --> EMIT
    EMIT --> OK(["done — log model, ttft, total, chars"])

    RES -->|"error, nothing emitted yet"| PERM{"permanent?"}
    PERM -.- PERMNOTE["retired · gated · 403 · 404<br/>unauthorized · model_not_supported"]
    PERM -->|no| RETRY{"retries left?"}
    RETRY -->|"yes, up to MAX_RETRIES"| BACK["sleep retry_backoff · 2^n + jitter<br/>so concurrent callers do not stampede"]
    BACK --> CALL
    RETRY -->|no| NEXT["advance to the next candidate model"]
    PERM -->|yes| NEXT
    NEXT --> MORE{"candidates<br/>remaining?"}
    MORE -->|yes| CALL
    MORE -->|no| DEAD(["LLMError → 502 on /chat,<br/>event: error on /chat/stream"])

    RES -->|"error after tokens were sent"| ABORT(["surfaced immediately —<br/>restarting elsewhere would<br/>duplicate half a sentence"])

    classDef step fill:#04261c,stroke:#3fb950,color:#c8f2d5,stroke-width:1px
    classDef decision fill:#2a1f05,stroke:#d29922,color:#f7e3ad,stroke-width:1px
    classDef term fill:#1d1233,stroke:#a371f7,color:#e4d5ff,stroke-width:1px
    classDef bad fill:#2d0f1a,stroke:#f778ba,color:#ffd3e6,stroke-width:1px
    classDef note fill:#161b22,stroke:#6e7681,color:#c9d1d9,stroke-width:1px

    class PICK,CALL,EMIT,PROMOTE,BACK,NEXT step
    class RES,FIRST,PERM,RETRY,MORE decision
    class START,OK term
    class DEAD,ABORT bad
    class PERMNOTE note

    linkStyle default stroke:#8b949e,stroke-width:1.4px
```

### Trust boundary

The frontend assigns replies with `innerHTML`, so everything crossing back from
the model is treated as hostile until it has been through `rendering.py`.

```mermaid
%%{init: {"theme":"base","themeVariables":{"fontSize":"13px","primaryColor":"#161b22","mainBkg":"#161b22","primaryTextColor":"#e6edf3","tertiaryTextColor":"#e6edf3","primaryBorderColor":"#30363d","lineColor":"#8b949e","textColor":"#e6edf3","titleColor":"#e6edf3","clusterBkg":"#0d1117","clusterBorder":"#30363d","edgeLabelBackground":"#161b22"}}}%%
flowchart LR
    subgraph UNTRUSTED["UNTRUSTED"]
        RAW["model output<br/>may contain script tags,<br/>event handlers, javascript: URLs"]
    end

    subgraph SERVER["SERVER-SIDE SANITISATION · rendering.py"]
        direction TB
        S1["markdown2 safe_mode='escape'<br/>raw HTML is escaped before parsing"]
        S2["bleach.clean — tag allowlist,<br/>attribute allowlist, strip=True"]
        S3["bleach.linkify — target=_blank,<br/>rel=noopener noreferrer nofollow"]
        S1 --> S2 --> S3
    end

    subgraph TRUSTED["TRUSTED"]
        SAFE["ChatResponse.response<br/>safe to inject"]
    end

    subgraph DEFENCE["DEFENCE IN DEPTH"]
        direction TB
        CSP["Content-Security-Policy<br/>default-src 'self' · object-src 'none'<br/>frame-ancestors 'none' · base-uri 'self'"]
        HDR["nosniff · X-Frame-Options DENY<br/>Referrer-Policy · Permissions-Policy · COOP"]
        DELTA["streamed deltas are painted as<br/>textContent, never as markup"]
    end

    RAW --> S1
    S3 --> SAFE
    SAFE --> DOM["browser innerHTML"]
    DELTA -.-> DOM
    CSP -.->|"blocks anything that slips through"| DOM
    HDR -.-> DOM

    classDef bad fill:#2d0f1a,stroke:#f778ba,color:#ffd3e6,stroke-width:1px
    classDef step fill:#04261c,stroke:#3fb950,color:#c8f2d5,stroke-width:1px
    classDef term fill:#1d1233,stroke:#a371f7,color:#e4d5ff,stroke-width:1px
    classDef edgec fill:#2a1f05,stroke:#d29922,color:#f7e3ad,stroke-width:1px

    class RAW bad
    class S1,S2,S3 step
    class SAFE,DOM term
    class CSP,HDR,DELTA edgec

    style UNTRUSTED fill:#0d1117,stroke:#f778ba,color:#ff9bce
    style SERVER fill:#0d1117,stroke:#3fb950,color:#56d364
    style TRUSTED fill:#0d1117,stroke:#a371f7,color:#c297ff
    style DEFENCE fill:#0d1117,stroke:#d29922,color:#e3b341

    linkStyle default stroke:#8b949e,stroke-width:1.4px
```

### Build and deployment

```mermaid
%%{init: {"theme":"base","themeVariables":{"fontSize":"13px","primaryColor":"#161b22","mainBkg":"#161b22","primaryTextColor":"#e6edf3","tertiaryTextColor":"#e6edf3","primaryBorderColor":"#30363d","lineColor":"#8b949e","textColor":"#e6edf3","titleColor":"#e6edf3","clusterBkg":"#0d1117","clusterBorder":"#30363d","edgeLabelBackground":"#161b22"}}}%%
flowchart LR
    subgraph CI["GITHUB ACTIONS · ENABLE_RETRIEVAL=false keeps it offline"]
        direction TB
        Q["quality<br/>ruff check · ruff format --check"]
        T["test<br/>pytest + coverage on 3.12 and 3.13"]
        DK["docker<br/>buildx build, run, poll /health for 60s"]
    end

    subgraph IMG["DOCKER · two stages, python:3.13-slim on both sides"]
        direction TB
        B1["builder<br/>uv venv + uv pip install -r pyproject.toml<br/>cached until pyproject.toml changes"]
        B2["runtime<br/>copies /app/.venv + source only —<br/>no uv, no compilers, no build cache"]
        B3["uid 1000 'user' created before USER<br/>HF_HOME under /home/user"]
        B1 --> B2 --> B3
    end

    DEV(["push / pull request"]) --> CI
    CI --> IMG
    IMG --> RUN["uvicorn application:app<br/>--proxy-headers --timeout-graceful-shutdown 20"]
    RUN --> HC["HEALTHCHECK /health<br/>start-period 180s covers a cold index build"]
    RUN --> SPACE(["Hugging Face Spaces<br/>or any container host, port 7860"])

    classDef step fill:#04261c,stroke:#3fb950,color:#c8f2d5,stroke-width:1px
    classDef term fill:#1d1233,stroke:#a371f7,color:#e4d5ff,stroke-width:1px
    classDef img fill:#0b1f3a,stroke:#2f81f7,color:#cfe3ff,stroke-width:1px

    class Q,T,DK step
    class B1,B2,B3 img
    class DEV,SPACE,RUN,HC term

    style CI fill:#0d1117,stroke:#3fb950,color:#56d364
    style IMG fill:#0d1117,stroke:#2f81f7,color:#79c0ff

    linkStyle default stroke:#8b949e,stroke-width:1.4px
```

---

## Project structure

```
application.py               # entrypoint (uvicorn application:app)
app/
  __init__.py                # __version__
  config.py                  # env-backed Settings, lru_cached
  main.py                    # app factory + lifespan wiring
  middleware.py              # CSP/security headers + sliding-window rate limit
  observability.py           # request-id ContextVar, JSON/text logging
  prompts.py                 # system prompt / message assembly
  schemas.py                 # request + response models
  routers/
    chat.py                  # POST /chat, /chat/stream, /chat/reset
    pages.py                 # GET /, /health
  services/
    chat.py                  # route -> retrieve -> prompt -> generate -> render
    llm.py                   # async HF client, retries, sticky failover
    retrieval.py             # TF-IDF index + domain routing over both datasets
    rendering.py             # Markdown -> sanitised HTML
    safety.py                # crisis detection + helpline notice
    sessions.py              # in-memory conversation history (LRU + TTL)
static/
  css/style.css              # design tokens + all UI styling
  js/api.js                  # fetch + SSE parsing
  js/store.js                # conversation persistence (localStorage)
  js/ui.js                   # toasts, dialogs, icons, time formatting
  js/app.js                  # wiring
templates/index.html         # chat UI
tests/
  conftest.py                # stub LLM + offline app fixture
  test_api.py                # endpoints, validation, history threading
  test_services.py           # routing, retrieval, prompts, safety, sanitising
  test_resilience.py         # failover, retries, headers, rate limiting
DockerFile                   # two-stage uv build
.github/workflows/ci.yml     # lint · test matrix · docker build + boot check
```

## Requirements

- Python 3.12+ (numpy 2.5 dropped 3.11)
- A Hugging Face token with inference access

## Installation

```bash
git clone https://github.com/noumanh11/HarmonyBot-v1.0.git
cd HarmonyBot-v1.0

python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate

pip install -r Requirements.txt

cp .env.example .env          # then add your HF_TOKEN
```

Run it:

```bash
uvicorn application:app --host 127.0.0.1 --port 7860
```

Open <http://127.0.0.1:7860>. First start takes a few seconds while the
datasets download and the index builds — it runs on a worker thread, so the
server accepts requests immediately and simply answers without retrieval until
the index is ready. Set `ENABLE_RETRIEVAL=false` to skip it entirely.

<details>
<summary>Using <code>uv</code> instead</summary>

```bash
uv sync --extra dev
uv run uvicorn application:app --port 7860
```

This is what CI does, and it keeps everything inside the project venv.
</details>

## Configuration

Every setting is an environment variable, read by `app/config.py` from the
process environment or a local `.env`. List-valued settings are parsed as JSON,
e.g. `CORS_ORIGINS='["https://example.com"]'`.

**Hugging Face**

| Variable | Default | Purpose |
|---|---|---|
| `HF_TOKEN` | — | Inference token (required for real generation) |
| `MODEL_ID` | `meta-llama/Llama-3.1-8B-Instruct` | Primary model on HF Inference Providers |
| `FALLBACK_MODELS` | `["Qwen/Qwen2.5-7B-Instruct", "meta-llama/Llama-3.3-70B-Instruct"]` | Tried in order when the primary is retired, gated or overloaded |
| `REQUEST_TIMEOUT` | `60.0` | Per-request timeout, seconds |
| `MAX_RETRIES` | `2` | Retries per model for *transient* failures only |
| `RETRY_BACKOFF` | `0.5` | Base for exponential backoff with jitter |

**Generation**

| Variable | Default | Purpose |
|---|---|---|
| `MAX_TOKENS` | `512` | Reply length ceiling |
| `TEMPERATURE` | `0.7` | Sampling temperature |

**Retrieval**

| Variable | Default | Purpose |
|---|---|---|
| `ENABLE_RETRIEVAL` | `true` | Set `false` to boot without the datasets |
| `MEDICAL_DATASET` | `avaliev/chat_doctor` | Medical corpus |
| `MENTAL_HEALTH_DATASET` | `Amod/mental_health_counseling_conversations` | Counselling corpus |
| `MAX_INDEX_ROWS` | `20000` | Rows indexed per corpus |
| `TOP_K` | `2` | Examples injected per question |
| `MIN_SIMILARITY` | `0.12` | Floor below which examples are discarded |

**Conversation memory**

| Variable | Default | Purpose |
|---|---|---|
| `MAX_HISTORY_TURNS` | `8` | Server-side memory window (one turn = user + bot) |
| `SESSION_TTL_SECONDS` | `3600` | Idle lifetime of a session |
| `MAX_SESSIONS` | `1000` | LRU cap, so memory cannot grow without bound |

**Server and operations**

| Variable | Default | Purpose |
|---|---|---|
| `HOST` / `PORT` | `127.0.0.1` / `7860` | Bind address |
| `CORS_ORIGINS` | `[]` | CORS is only mounted when this is non-empty |
| `LOG_LEVEL` | `INFO` | Root log level |
| `JSON_LOGS` | `false` | JSON lines for a log platform; text locally |
| `RATE_LIMIT_REQUESTS` | `20` | Requests per window, per client |
| `RATE_LIMIT_WINDOW_SECONDS` | `60.0` | Sliding-window length |
| `SECURITY_HEADERS` | `true` | Toggle the CSP / hardening middleware |

## API

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/` | Chat UI |
| `GET` | `/health` | Status, version, **active** model, retrieval readiness, indexed docs |
| `POST` | `/chat` | Complete reply as sanitised HTML |
| `POST` | `/chat/stream` | Same pipeline, streamed as SSE |
| `POST` | `/chat/reset` | Clear a session's history (`204`) |
| `GET` | `/docs` | OpenAPI documentation |

`POST /chat` and `POST /chat/stream` accept:

```jsonc
{
  "message": "string, 1-4000 chars",         // required
  "session_id": "opaque id, <= 64 chars",    // optional; generated if absent
  "history": [                                // optional; <= 20 messages
    { "role": "user",      "content": "..." },
    { "role": "assistant", "content": "..." }
  ]
}
```

When `history` is present it **overrides** the server session — that is what
lets a conversation restored from `localStorage` keep its context across a
server restart, and keeps the server effectively stateless.

**SSE events** emitted by `/chat/stream`, in order:

| Event | Payload | Meaning |
|---|---|---|
| `session` | session id | Echoed so the client can thread later turns |
| `meta` | `medical` \| `mental_health` \| `general` | The routed domain |
| `crisis` | HTML | Helpline notice, emitted before generation |
| `delta` | text | One token chunk; the client paints it as plain text |
| `done` | HTML | Sanitised final reply, replaces the streamed text |
| `error` | text | Generic message; the detail is in the server log |

Every frame is `event: <name>\ndata: <json-string>\n\n`, JSON-encoded so a
newline inside the payload cannot break framing.

**Status codes**: `422` for malformed input (caught by pydantic at the edge),
`429` with `Retry-After` when rate limited, `502` when every candidate model
failed. Errors never leak the upstream exception string.

## Observability

- Every response carries `X-Request-ID`. An inbound `X-Request-ID` is honoured,
  so a trace survives a proxy hop.
- The id lives in a `ContextVar`, so it follows the request across `await`
  points without being threaded through every signature.
- `JSON_LOGS=true` emits one JSON object per line; anything passed via
  `extra=` becomes a first-class field. uvicorn's own loggers are routed
  through the same handler.
- Access logs skip `/static`, and generation logs record model, time-to-first-
  token, total duration and character count.

## Tests

```bash
pip install -r requirements-dev.txt
pytest -q
```

The suite runs fully offline against a stub model — no token, no downloads. It
covers the endpoints and their status codes, history threading and overrides,
domain routing, retrieval attribution and the similarity floor, prompt shape,
crisis detection (including false positives), XSS sanitisation, session
eviction, security headers, rate limiting, and the whole failover/retry matrix.

## Docker

```bash
docker build -t harmonybot -f DockerFile .
docker run -p 7860:7860 -e HF_TOKEN=your_token harmonybot
```

Two stages sharing one base image, so the venv copied across finds its
interpreter at the same path. The runtime stage carries only the venv and the
source, runs as uid 1000 (what Hugging Face Spaces expects), and declares a
`HEALTHCHECK` with a 180-second start period to cover a cold index build.

## How it works

1. **Route** — keyword vote across medical and mental-health vocabularies,
   falling back to retrieval similarity when no keyword matches.
2. **Retrieve** — TF-IDF cosine search over the *question* side of the chosen
   corpus, discarding anything below the similarity floor.
3. **Prompt** — persona and reference examples go in a `system` message; the
   user's question stays its own `user` message so the model can tell them
   apart.
4. **Generate** — streamed from the model, token by token, with failover.
5. **Render** — Markdown converted, escaped, and whitelisted before display.

Datasets: [`avaliev/chat_doctor`](https://huggingface.co/datasets/avaliev/chat_doctor)
and [`Amod/mental_health_counseling_conversations`](https://huggingface.co/datasets/Amod/mental_health_counseling_conversations).

## Upgrading from v1

v1 shipped several breaking defects, all fixed here:

- The pinned model (`Meta-Llama-3-8B-Instruct`) was retired from HF Inference
  Providers and returned `model_not_supported` on every request.
- `HF_HOME` was hardcoded to `/app/.cache`, which broke non-Docker runs and
  hid cached credentials.
- Retrieval always injected `train[0]`, so every medical question was answered
  against the same appendectomy case, and the dataset roles were swapped.
- Context, examples and the question were flattened into one `user` string, so
  the model frequently answered the *example* instead of the user.
- The sync inference client was called inside `async def`, blocking the event
  loop for the entire generation.
- Model output went into `innerHTML` unsanitised.
- The Exit button POSTed to `/shutdown`, which never existed.
- The Dockerfile ran `app:app` and set `USER user` without creating the user.

## Limitations

- Conversation history is per-process and in-memory; it does not survive a
  restart or span replicas. The browser copy does.
- Rate limiting is in-process, so it protects one worker, not a fleet.
- There is no authentication.
- Retrieval is lexical (TF-IDF), so paraphrases with no shared vocabulary can
  miss.
- **Not a medical device.** Do not use it for diagnosis or treatment decisions.

## What's upgradable

The seams are deliberately placed so these are swaps, not rewrites:

| Today | Next step |
|---|---|
| `SessionStore` — in-process dict | Redis-backed store behind the same three methods |
| `RateLimitMiddleware` — per-worker deque | Shared limiter at the edge, or Redis token bucket |
| TF-IDF `_Index` | Sentence-embedding index; `search()` keeps its signature |
| Single container | Multiple replicas, once session and rate-limit state are shared |

## Group members

Originally built together at
[shabihassan1/HarmonyBot-v1.0](https://github.com/shabihassan1/HarmonyBot-v1.0);
this repository is the v2 continuation.

1. **Shabi ul Hassan** — [LinkedIn](https://www.linkedin.com/in/shabi-ul-hassan1/)
2. **Abdullah Salman** — [LinkedIn](https://www.linkedin.com/in/abdullah-salman-89253b272/)
3. **Nouman Hafeez** — [LinkedIn](https://www.linkedin.com/in/noumanhafeez11nh/)

## Supervisor

**Dr. Mehreen Alam** — [LinkedIn](https://www.linkedin.com/in/dr-mehreen-alam-5a1b9720/)

## Video demonstration

[![HarmonyBot Video Demonstration](Thumbnail.png)](https://youtu.be/w5FbRiV-Vs4)

## License

Apache License 2.0 — see [LICENSE](LICENSE).
