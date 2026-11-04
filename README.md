# Lararium

<p align="center">
  <strong>A Personal Digital Garden & Academic Workbench</strong>
</p>

<p align="center">
  <a href="README.md">English</a> | <a href="README_zh.md">简体中文</a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11+-3776AB?style=flat&logo=python&logoColor=white" alt="Python 3.11+" />
  <img src="https://img.shields.io/badge/Vue.js-3.5+-4FC08D?style=flat&logo=vuedotjs&logoColor=white" alt="Vue 3" />
  <img src="https://img.shields.io/badge/FastAPI-0.115+-009688?style=flat&logo=fastapi&logoColor=white" alt="FastAPI" />
  <img src="https://img.shields.io/badge/Vite-6.0+-646CFF?style=flat&logo=vite&logoColor=white" alt="Vite" />
  <img src="https://img.shields.io/badge/Docker-Ready-2496ED?style=flat&logo=docker&logoColor=white" alt="Docker Ready" />
  <img src="https://img.shields.io/badge/License-MIT-blue.svg" alt="License: MIT" />
</p>

---

## 🏛️ What is Lararium?

In classical Roman antiquity, the **Lararium** was the sacred domestic shrine dedicated to the guardian spirits of the home—safeguarding intimate family treasures and private sanctums.

**Lararium** (formerly *Kruskal*) brings notes, whiteboards, paper reading, schedules, and everyday records together in a personal workspace.

---

## ✨ Key Features

### 🖊️ Write on a whiteboard

Turn PDF handouts and PPTX slides into multi-page notes and write directly on them. Use a pen, highlighter, eraser, and images; undo edits or add extra space beside a page for your own notes.

### 📚 Organize notes and read papers

Write Markdown notes with formulas and tables, organize them into folders, search across your collection, and export notes to PDF. Read papers with highlighting and word lookup or translation, and import metadata from an arXiv ID.

### 🤖 Keep track of information with the assistant

Collect notices and materials, search and organize cards, and follow deadlines from related updates. Open the calendar or start a note from an item, and ask questions about collected information. AI features require a configured model service.

### 📅 Plan and record your days

Use the calendar for events and deadlines, check off tasks, and see activity on a heatmap. Keep a diary, manage a ledger, save photos and memories, and review vocabulary or IELTS study materials.

### 📂 Read and edit project documents

Open Markdown files from project directories in the same interface. Browse, search, read formulas and images, and edit the original files; a conflict prompt helps when a file has changed elsewhere.

---

## 📐 Architecture Overview

```text
       Browser Client (SPA)
  [Vue 3 + TypeScript + Vite 6]
  [Element Plus + ECharts + KaTeX]
  [WebWorker Offscreen Whiteboard]
                │
                │ HTTP REST / Stream
                ▼
        FastAPI Gateway (:18080 locally)
┌───────────────────────────────────────┐
│ Global Auth & Session Vault Middleware│
│ - AES-256-GCM Envelope Encryption    │
│ - Password or local key management    │
│ - Lock Guard & Threadpool Executors   │
└───────────────────────────────────────┘
        │                       │
        ▼                       ▼
SQLite Metadata DB        Encrypted Vault Storage
(data/site.db)            (data/notes/, etc.)
```

---

## 🚀 Quick Start

### Windows local setup

Run `start.bat` or launch `start_silent.vbs` in the background, then open <http://127.0.0.1:18080/>. These launchers set `KRUSKAL_LOCAL_NO_PASSWORD=1`; no username or password is required. Existing password-protected data needs an explicit key migration before using this mode.

### Docker deployment (password authentication)

1. Clone the repository:
   ```bash
   git clone https://github.com/wangr9577-tech/lararium.git
   cd lararium
   ```

2. Start the service using Docker Compose:
   ```bash
   docker compose up -d
   ```

3. Open `http://127.0.0.1:8000`. The server deployment uses password authentication by default; its initial credentials are written to `initial_password.txt` in the configured data directory.

---

### Option B: Bare-Metal Setup (Development)

#### 1. Backend Setup
```bash
# Recommended: Python 3.11+
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

pip install -r backend/requirements.txt
```

#### 2. Frontend Build
```bash
cd frontend
npm install
npm run build
cd ..
```

#### 3. Run Server
```bash
uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 18080
```

---

## ⚙️ Environment Configuration

Copy the example environment file:
```bash
cp .env.example .env
```

| Variable | Default | Description |
| :--- | :--- | :--- |
| `KRUSKAL_DATA_DIR` | `backend/data` | Directory where SQLite DB and encrypted vault files reside. |
| `KRUSKAL_LOCAL_NO_PASSWORD` | unset | `1` enables the Windows launchers' local passwordless mode; use only with a prepared local data directory. |
| `KRUSKAL_PORT` | `18080` | Default port for the local web gateway. |
| `AI_ENDPOINT` | `http://127.0.0.1:11434/v1` | OpenAI-compatible endpoint for LLM features (e.g. Ollama, vLLM). |
| `AI_MODEL` | `qwen2.5:7b` | Model identifier for assistant summarization. |

---

## 🔒 Security & Privacy Model

- **Zero Third-Party Telemetry**: Lararium sends no telemetry, tracker beacons, or external analytic pings.
- **Client-Side Protection**: Strict Content Security Policy (CSP), DOMPurify sanitization, and timing-safe token verifications.
- **Scoped Local Binding**: Recommended for private deployment bound to `127.0.0.1` and accessed via authenticated SSH tunnels or Tailscale mesh networks.
- **Passwordless local keys**: In local mode, `.autokey` and `.kek.auto` are stored together in the data directory. Anyone able to read both files and the encrypted data can decrypt it. Keep both files in backups; losing them can make the data unreadable. This local mode is not intended for network exposure.
- **Independent deployments**: A server instance retains its own authentication and data. Local and server copies do not sync automatically.

---

## 📄 License & Attribution

This project is licensed under the **MIT License** - see the [LICENSE](LICENSE) file for details.

### Third-Party Notices
- **PyMuPDF**: Document processing utilizes PyMuPDF (licensed under AGPL-3.0 / Commercial). If you redistribute Lararium in a proprietary closed-source product, please verify compliance with Artifex licensing guidelines.
- **KaTeX**: Fast math typesetting licensed under the MIT License.
- **Element Plus**: UI component library licensed under the MIT License.

---

<p align="center">
  Crafted with care for personal autonomy, research clarity, and aesthetic peace.
</p>
