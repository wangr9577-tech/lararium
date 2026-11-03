# Lararium

<p align="center">
  <strong>A Sovereign Digital Garden & Academic Workbench with Zero-Trust Envelope Encryption</strong>
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

In the digital era, **Lararium** (formerly *Kruskal*) is an all-in-one, self-hosted personal operating system, academic digital garden, and knowledge hub. Built specifically for independent researchers, engineers, and digital minimalists, it integrates notes, slide-based whiteboards, literature appraisal, intelligent event reconciliation, accounting, and life tracking within a **strict AES-256-GCM envelope encryption boundary** and a visually captivating **anime-inspired glassmorphism interface**.

---

## ✨ Key Features

### 🛡️ 1. True Sovereign Data Privacy & Envelope Encryption
- **AES-256-GCM Encryption at Rest**: Markdown notes, daily footprints, private photos, and event cards are strictly encrypted on disk. Plaintext never leaks to unencrypted storage.
- **Lock-Guard Memory Defense**: Locking your workspace immediately zeroes memory Data Encryption Keys (DEKs). Background jobs pause with epoch tracking to prevent dirty writes.
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
        FastAPI Gateway (:8000)
┌───────────────────────────────────────┐
│ Global Auth & Session Vault Middleware│
│ - AES-256-GCM Envelope Encryption    │
│ - PBKDF2 / Argon2 DEK Derivation      │
│ - Lock Guard & Threadpool Executors   │
└───────────────────────────────────────┘
        │                       │
        ▼                       ▼
SQLite Metadata DB        Encrypted Vault Storage
(/app/data/kruskal.db)    (/app/data/*.enc, *.md)
```

---

## 🚀 Quick Start

### Option A: One-Click Docker Deployment (Recommended)

1. Clone the repository:
   ```bash
   git clone https://github.com/your-username/kruskal.git
   cd kruskal
   ```

2. Start the service using Docker Compose:
   ```bash
   docker compose up -d
   ```

3. Open your browser and navigate to `http://localhost:8000`. On first launch, follow the on-screen instructions to set up your master key and administrator password.

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
uvicorn backend.app.main:app --host 0.0.0.0 --port 8000
```

---

## ⚙️ Environment Configuration

Copy the example environment file:
```bash
cp .env.example .env
```

| Variable | Default | Description |
| :--- | :--- | :--- |
| `KRUSKAL_DATA_DIR` | `./data` | Directory where SQLite DB and encrypted vault files reside. |
| `KRUSKAL_PORT` | `8000` | Port for the web gateway. |
| `AI_ENDPOINT` | `http://127.0.0.1:11434/v1` | OpenAI-compatible endpoint for LLM features (e.g. Ollama, vLLM). |
| `AI_MODEL` | `qwen2.5:7b` | Model identifier for assistant summarization. |

---

## 🔒 Security & Privacy Model

- **Zero Third-Party Telemetry**: Lararium sends no telemetry, tracker beacons, or external analytic pings.
- **Client-Side Protection**: Strict Content Security Policy (CSP), DOMPurify sanitization, and timing-safe token verifications.
- **Scoped Local Binding**: Recommended for private deployment bound to `127.0.0.1` and accessed via authenticated SSH tunnels or Tailscale mesh networks.

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
