#!/usr/bin/env python3
"""
ChatBob — IBM Bob Shell backend (Python)
Uses only Python standard library. No pip install needed.

bob -p "<prompt>" runs non-interactively and streams plain text to stdout.
We pipe each chunk to the browser as an SSE event immediately,
giving a true streaming / typewriter effect.

Usage:
  python3 server.py
  PORT=8080 python3 server.py
  BOB_PATH=/custom/path/to/bob python3 server.py
"""

import http.server
import json
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

# ─── Config ───────────────────────────────────────────────────────────────────
BASE_DIR    = Path(__file__).parent.resolve()
PUBLIC_DIR  = BASE_DIR / 'public'
CONFIG_PATH = BASE_DIR / 'config.json'

# ─── In-memory task ID store (chatId → bobTaskId) ─────────────────────────────
_task_ids: dict = {}  # { chatId: task_id }
_task_ids_lock = threading.Lock()

file_config: dict = {}
try:
    file_config = json.loads(CONFIG_PATH.read_text())
    print(f'[config] loaded {CONFIG_PATH}')
except Exception:
    print(f'[config] {CONFIG_PATH} not found or invalid — using env only', file=sys.stderr)

# Env vars take precedence over config.json
CONFIG = {**file_config, **os.environ}

PORT = int(CONFIG.get('PORT', 3000))

def _find_bob() -> str:
    if 'BOB_PATH' in os.environ:
        return os.environ['BOB_PATH']
    candidates = [
        Path.home() / '.local' / 'bin' / 'bob',   # official installer (bobshell.sh)
        Path('/usr/local/bin/bob'),
        Path('/opt/homebrew/bin/bob'),
        Path.home() / '.npm-global' / 'bin' / 'bob',
    ]
    for c in candidates:
        if c.is_file() and os.access(c, os.X_OK):
            return str(c)
    return 'bob'

BOB_PATH = _find_bob()

# ─── MIME types ───────────────────────────────────────────────────────────────
MIME = {
    '.html': 'text/html; charset=utf-8',
    '.js':   'application/javascript; charset=utf-8',
    '.css':  'text/css; charset=utf-8',
    '.ico':  'image/x-icon',
    '.png':  'image/png',
    '.svg':  'image/svg+xml',
    '.json': 'application/json',
}

# ─── Run bob and stream output as SSE ─────────────────────────────────────────
def run_bob_streaming(prompt: str, system_prompt: Optional[str], chat_id: Optional[str], wfile, stop_event: threading.Event):
    full_prompt = f'[System: {system_prompt}]\n\n{prompt}' if system_prompt else prompt

    env = {**os.environ}
    # Ensure bob binary location is always on PATH
    env['PATH'] = str(Path.home() / '.local' / 'bin') + ':' + env.get('PATH', '')
    # Forward API key so bob can authenticate inside the container
    if CONFIG.get('BOB_API_KEY'):
        env['BOB_API_KEY'] = CONFIG['BOB_API_KEY']
    # bob needs HOME to locate its config/auth files
    env.setdefault('HOME', str(Path.home()))

    # Resolve existing task ID for this chat (enables conversation continuity via -r)
    existing_task_id: Optional[str] = None
    if chat_id:
        with _task_ids_lock:
            existing_task_id = _task_ids.get(chat_id)

    resume_flag = f' -r {json.dumps(existing_task_id)}' if existing_task_id else ''

    print(f"\n{'─' * 60}")
    print(f"[bob →] chatId={chat_id}  taskId={existing_task_id or '(new)'}  prompt: {full_prompt[:200]}{'…' if len(full_prompt) > 200 else ''}")
    print('─' * 60)

    try:
        process = subprocess.Popen(
            ['bash', '-c', f'{json.dumps(BOB_PATH)} run -f stream-json{resume_flag} {json.dumps(full_prompt)}'],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
    except Exception as e:
        payload = json.dumps({'choices': [{'delta': {'content': f'\n\n❌ Failed to run bob: {e}'}}]})
        wfile.write(f'data: {payload}\n\ndata: [DONE]\n\n'.encode())
        wfile.flush()
        return

    # Stream stderr in background so it doesn't block stdout
    def _drain_stderr():
        for line in process.stderr:
            sys.stderr.buffer.write(b'[bob stderr] ' + line)
            sys.stderr.buffer.flush()

    threading.Thread(target=_drain_stderr, daemon=True).start()

    line_buf = ''
    done = False
    try:
        for chunk in iter(lambda: process.stdout.read(256), b''):
            if stop_event.is_set() or done:
                process.kill()
                break
            line_buf += chunk.decode('utf-8', errors='replace')
            # process every complete newline-delimited JSON line
            while '\n' in line_buf:
                line, line_buf = line_buf.split('\n', 1)
                line = line.strip()
                if not line:
                    continue
                sys.stdout.write(f'[bob] {line}\n')
                sys.stdout.flush()
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if event.get('type') == 'message' and event.get('role') == 'assistant' and event.get('content'):
                    payload = json.dumps({'choices': [{'delta': {'content': event['content']}}]})
                    wfile.write(f'data: {payload}\n\n'.encode())
                    wfile.flush()
                elif event.get('type') == 'result':
                    new_task_id = event.get('stats', {}).get('task_id')
                    print(f"[bob] status={event.get('status')}  task_id={new_task_id}")
                    # Store the task ID and notify the frontend so subsequent turns resume the conversation
                    if new_task_id and chat_id:
                        with _task_ids_lock:
                            _task_ids[chat_id] = new_task_id
                        taskid_payload = json.dumps({'taskId': new_task_id})
                        try:
                            wfile.write(f'event: taskid\ndata: {taskid_payload}\n\n'.encode())
                            wfile.flush()
                        except (BrokenPipeError, ConnectionResetError):
                            pass
                    done = True
                    break
    except (BrokenPipeError, ConnectionResetError):
        process.kill()
    finally:
        process.wait()
        print(f'[bob] exited  code={process.returncode}')
        try:
            wfile.write(b'data: [DONE]\n\n')
            wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass

# ─── Request handler ──────────────────────────────────────────────────────────
class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # suppress default access log; we print our own

    def _cors_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET,POST,OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors_headers()
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path

        # GET /api/config
        if path == '/api/config':
            bob_found = os.path.isfile(BOB_PATH) and os.access(BOB_PATH, os.X_OK)
            self._json(200, {'configured': bob_found, 'bobPath': BOB_PATH})
            return

        # Static files
        if path in ('/', '/index.html'):
            file_path = PUBLIC_DIR / 'index.html'
        else:
            file_path = (PUBLIC_DIR / path.lstrip('/')).resolve()

        # Path traversal guard
        try:
            file_path.relative_to(PUBLIC_DIR)
        except ValueError:
            self.send_response(403)
            self.end_headers()
            return

        if not file_path.is_file():
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b'Not found')
            return

        mime = MIME.get(file_path.suffix, 'application/octet-stream')
        data = file_path.read_bytes()
        self.send_response(200)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        path = urlparse(self.path).path

        # POST /api/chat
        if path == '/api/chat':
            length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(length)
            try:
                parsed = json.loads(body)
            except json.JSONDecodeError:
                self._json(400, {'error': 'Invalid JSON'})
                return

            prompt        = parsed.get('prompt', '').strip()
            system_prompt = parsed.get('systemPrompt')
            chat_id       = parsed.get('chatId') or None
            if not prompt:
                self._json(400, {'error': 'prompt is required'})
                return

            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Cache-Control', 'no-cache')
            self.send_header('Connection', 'keep-alive')
            self._cors_headers()
            self.end_headers()

            stop_event = threading.Event()
            run_bob_streaming(prompt, system_prompt, chat_id, self.wfile, stop_event)
            return

        # POST /api/taskid — frontend stores a task ID it learned about
        if path == '/api/taskid':
            length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(length)
            try:
                parsed = json.loads(body)
            except json.JSONDecodeError:
                self._json(400, {'error': 'Invalid JSON'})
                return
            cid = parsed.get('chatId')
            tid = parsed.get('taskId')
            if cid and tid:
                with _task_ids_lock:
                    _task_ids[cid] = tid
            self._json(200, {'ok': True})
            return

        self._json(404, {'error': 'Not found'})

    def do_DELETE(self):
        path = urlparse(self.path).path

        # DELETE /api/taskid/<chatId>
        if path.startswith('/api/taskid/'):
            chat_id = path[len('/api/taskid/'):]
            if chat_id:
                with _task_ids_lock:
                    _task_ids.pop(chat_id, None)
            self._json(200, {'ok': True})
            return

        self._json(404, {'error': 'Not found'})

    def _json(self, status: int, data: dict):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self._cors_headers()
        self.end_headers()
        self.wfile.write(body)


# ─── Start ────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    server = http.server.ThreadingHTTPServer(('', PORT), Handler)
    print(f'\n╔════════════════════════════════════════════╗')
    print(f'║         ChatBob — IBM Bob Chat UI          ║')
    print(f'╠════════════════════════════════════════════╣')
    print(f'║  Local:   http://localhost:{PORT}              ║')
    print(f'║  Backend: bob run -f stream-json         ║')
    print(f'║  Bob:     {BOB_PATH:<40} ║')
    print(f'╚════════════════════════════════════════════╝\n')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\n[server] stopped')
