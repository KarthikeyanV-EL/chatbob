# ChatBob 🤖

A **ChatGPT-style web interface** for [IBM Bob](https://bob.ibm.com) — your AI software development partner.

Backend is a single-file Python 3 server (`server.py`) with zero pip dependencies.

---

## Quick start — Docker (recommended)

```bash
# Build
docker build -t chatbob-ui .

# Run (pass your Bob API key as an env var)
docker run --rm -p 3000:3000 -e BOB_API_KEY=your_key chatbob-ui

# Open
open http://localhost:3000
```

> Bob Shell is installed inside the image via the official installer:
> `curl -fsSL https://bob.ibm.com/download/bobshell.sh | bash`

---

## Quick start — local (Python 3, no install)

```bash
cd chatbob-ui
export BOB_API_KEY="your_key"
python3 server.py
open http://localhost:3000
```

Bob Shell must already be installed on your machine:
```bash
curl -fsSL https://bob.ibm.com/download/bobshell.sh | bash
```

---

## Configuration

| Variable      | Default  | Description                          |
|---------------|----------|--------------------------------------|
| `BOB_API_KEY` | —        | Your IBM Bob API key                 |
| `BOB_PATH`    | auto     | Path to the `bob` binary (optional)  |
| `PORT`        | `3000`   | Port the server listens on           |

Secrets can also be placed in a `config.json` file (git-ignored):
```json
{ "BOB_API_KEY": "your_key" }
```

Mount it at runtime so it is never baked into the image:
```bash
docker run --rm -p 3000:3000 \
  -v $(pwd)/config.json:/app/config.json:ro \
  chatbob-ui
```

---

## Project structure

```
chatbob-ui/
├── Dockerfile       # Single-stage Python image; installs Bob Shell
├── .dockerignore
├── server.py        # Python 3 backend — zero pip dependencies
├── package.json     # Convenience npm scripts (docker:build, docker:run)
└── public/
    └── index.html   # Single-page chat UI (self-contained)
```

### How it works

```
Browser ──POST /api/chat──▶ server.py ──bob -f stream-json -p "…"──▶ Bob Shell
        ◀── SSE stream ───            ◀── stdout (NDJSON) ──────────
```

`server.py` spawns `bob` as a subprocess, parses the newline-delimited JSON it
emits, and forwards assistant tokens to the browser as Server-Sent Events.
Conversation continuity is maintained via the `-r <task_id>` flag — the
`task_id` returned in each `result` event is stored server-side and reused on
the next turn for the same chat.

---

## Keyboard shortcuts

| Key             | Action       |
|-----------------|--------------|
| `Enter`         | Send message |
| `Shift + Enter` | New line     |

---

## License

MIT
