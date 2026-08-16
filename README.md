# Harmony Bot v2.0

**Harmony Bot** is a conversational assistant for medical and mental-health
questions. It routes each question to a domain, retrieves genuinely similar
examples from two Hugging Face datasets, and answers with a Llama-3.1 model
served through the Hugging Face Inference API.

## Features

- **Retrieval-grounded answers** — TF-IDF nearest-neighbour search over ~23k
  real patient/counsellor exchanges, so the injected context actually relates
  to the question.
- **Live token streaming** — replies render as they are generated over SSE.
- **Conversation memory** — a rolling window of recent turns, per session.
- **Crisis safeguards** — deterministic detection of self-harm language, with
  helpline resources surfaced before the model is even called.
- **Sanitised output** — model Markdown is escaped and whitelisted before it
  reaches the DOM.
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

## Project structure

```
application.py             # entrypoint (uvicorn application:app)
app/
  config.py                # env-backed settings
  main.py                  # app factory + lifespan wiring
  prompts.py               # system prompt / message assembly
  schemas.py               # request + response models
  routers/
    chat.py                # POST /chat, /chat/stream, /chat/reset
    pages.py               # GET /, /health
  services/
    chat.py                # route -> retrieve -> prompt -> generate -> render
    llm.py                 # async Hugging Face client
    retrieval.py           # TF-IDF index over both datasets
    rendering.py           # Markdown -> sanitised HTML
    safety.py              # crisis detection
    sessions.py            # in-memory conversation history
static/
  css/style.css            # design tokens + all UI styling
  js/api.js                # fetch + SSE parsing
  js/store.js              # conversation persistence (localStorage)
  js/ui.js                 # toasts, dialogs, icons, time formatting
  js/app.js                # wiring
templates/index.html       # chat UI
tests/                     # pytest suite
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
datasets download and the index builds; set `ENABLE_RETRIEVAL=false` to skip
that entirely.

## Configuration

Every setting is an environment variable — see `.env.example`. The ones worth
knowing:

| Variable | Default | Purpose |
|---|---|---|
| `HF_TOKEN` | — | Hugging Face inference token (required) |
| `MODEL_ID` | `meta-llama/Llama-3.1-8B-Instruct` | Any model on HF Inference Providers |
| `ENABLE_RETRIEVAL` | `true` | Set `false` to boot without the datasets |
| `MAX_INDEX_ROWS` | `20000` | Rows indexed from the medical corpus |
| `TOP_K` | `2` | Examples injected per question |
| `MIN_SIMILARITY` | `0.12` | Floor below which examples are discarded |
| `MAX_HISTORY_TURNS` | `8` | Conversation memory window |

## API

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/` | Chat UI |
| `GET` | `/health` | Readiness, model, index size |
| `POST` | `/chat` | Complete reply as sanitised HTML |
| `POST` | `/chat/stream` | Same pipeline, streamed as SSE |
| `POST` | `/chat/reset` | Clear a session's history |
| `GET` | `/docs` | OpenAPI documentation |

## Tests

```bash
pip install -r requirements-dev.txt
pytest -q
```

The suite runs fully offline against a stub model — no token, no downloads.

## Docker

```bash
docker build -t harmonybot .
docker run -p 7860:7860 -e HF_TOKEN=your_token harmonybot
```

## How it works

1. **Route** — keyword vote across medical and mental-health vocabularies,
   falling back to retrieval similarity when no keyword matches.
2. **Retrieve** — TF-IDF cosine search over the *question* side of the chosen
   corpus, discarding anything below the similarity floor.
3. **Prompt** — persona and reference examples go in a `system` message; the
   user's question stays its own `user` message so the model can tell them
   apart.
4. **Generate** — streamed from the model, token by token.
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
- Model output went into `innerHTML` unsanitised.
- The Exit button POSTed to `/shutdown`, which never existed.
- The Dockerfile ran `app:app` and set `USER user` without creating the user.

## Limitations

- Conversation history is per-process and in-memory; it does not survive a
  restart or span replicas.
- There is no authentication or rate limiting.
- Retrieval is lexical (TF-IDF), so paraphrases with no shared vocabulary can
  miss.
- **Not a medical device.** Do not use it for diagnosis or treatment decisions.

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
