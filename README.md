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

In the digital era, **Lararium** (formerly *Kruskal*) is a self-hosted personal workspace for notes, whiteboards, research, schedules, and daily life. Content is encrypted at rest; the Windows local setup uses passwordless access with a locally stored key.

---

## ✨ Key Features

### 🛡️ 1. Encrypted Storage & Passwordless Local Access
- **AES-256-GCM Encryption at Rest**: Notes and other private content use encrypted storage.
- **Local passwordless access**: Windows launchers unlock data with a local key and create a local browser session automatically. Password-based deployments retain the lock feature.
- **Local key protection**: The local key is stored alongside the data, so anyone who can access both can decrypt the content. Protect the data directory and backups.
- **Atomic File System**: All writes enforce atomic replace semantics (`fsync` + temporary staging files), eliminating file corruption during unexpected power cuts.

### 🖊️ 2. Offscreen Canvas Whiteboard & Courseware Ingestion
- **Multi-layer Offscreen Inking**: Powered by WebWorkers and `perfect-freehand`, delivering pressure-sensitive, anti-aliased pen strokes with instant rendering.
- **Pure Python PPTX/PDF Ingestion**: Converts `.pptx` slides directly to high-fidelity SVG vector pages and rasterizes `.pdf` courseware into multi-page writeable boards with zero external binaries (no LibreOffice, Poppler, or headless Chromium required).

### 🔬 3. Zero-Copy Research Workspace & External Project Mounting
- **Direct Workspace Linking**: Mount real Markdown directories from external repositories into your workbench. No duplicated storage.
- **Bi-directional Backlinks & Conflict Guard**: Tracks bidirectional wiki-style backlinks (`[[Title]]`), while SHA-256 content hashes prevent concurrent overwrites from AI coding agents or local editors.

### 🤖 4. Notification Intelligence & Task Reconciliation
- **Automated Event Extraction**: Feeds unstructured campus/work notices into local or remote LLMs (Qwen, DeepSeek) to automatically track deadlines and requirements.
- **Single Source of Truth**: Reconciles postponements and revisions across incoming announcements without polluting schedules with duplicate tasks.

### 🌌 5. Complete Life Operating Suite
- **Ledger**: Exact-cent financial tracking with debt channels, multi-currency support, and audit snapshots.
- **Daily Footprint & Diary**: Daily journal aggregating completed schedule tasks, financial expenses, and research milestones.
- **Vocabulary & Language Learning**: Leitner spaced-repetition box system and IELTS 4-skill timeline review.
- **Encrypted Photo Album**: Encrypted image storage with duplicate detection and atomic rollback guards.

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

### Windows local setup (passwordless)

Run `start.bat` or launch `start_silent.vbs` in the background, then open <http://127.0.0.1:18080/>. These launchers set `KRUSKAL_LOCAL_NO_PASSWORD=1`; no username or password is required. Existing password-protected data needs an explicit key migration before using this mode.

### Docker deployment (password authentication)

1. Clone the repository:
   ```bash
   git clone https://github.com/your-username/kruskal.git
   cd kruskal
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
