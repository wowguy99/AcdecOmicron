# AcDec Atomic Flashcard CSV Generator

A local web app that turns Academic Decathlon (AcDec) curriculum PDFs into
hyper-granular, atomic Anki flashcards, organized in a bottom-up "family tree"
you can download from at every tier.

It follows three principles:

- **Zero-loss**: every testable statistic, date, name, list, or fact becomes a
  standalone card (no summarizing).
- **Atomic**: each card tests exactly one fact, with a short question/answer.
- **Cumulative tracks**: **Track A** (text-only) and **Master / Track B**
  (Track A plus image/figure caption cards).

## How it works

```
Upload PDFs + tags -> span-level parse -> 3-tier blueprint -> approve (editable)
   -> bottom-up generation (AI for body/captions, deterministic for glossary/
      timeline) -> per-tier CSV downloads
```

Key design points (see `backend/app/parsing`):

- **Span-level, font-aware extraction** (PyMuPDF `get_text("dict")`) so footnote
  superscripts are dropped without corrupting real numbers, running
  headers/footers are removed by frequency, and printed page numbers map to PDF
  pages.
- **TOC-driven structure** with multi-column, wrapped-line, and 4-indent-level
  handling; tier-4 entries fold into their tier-3 parent (exactly 3 tiers).
- **Section-type classifier**: `GLOSSARY` and `TIMELINE` are parsed
  deterministically into cards (no AI, no hallucination); `NOTES`,
  `BIBLIOGRAPHY`, and `SECTION_SUMMARY` are excluded.
- **Resumable generation**: per-chunk status in SQLite, throttled to the
  provider's free-tier RPM/RPD (counted locally), with JSON parse/repair/retry.

## Requirements

- Python 3.11+
- Node 18+ (for building the frontend; only needed once)

## Setup

```bash
# 1. Backend deps (from repo root)
python -m venv .venv
.venv\Scripts\python -m pip install -r backend/requirements.txt   # Windows
# source .venv/bin/activate && pip install -r backend/requirements.txt   # macOS/Linux

# 2. Build the frontend (served by the backend at http://127.0.0.1:8000)
cd frontend
npm install
npm run build
cd ..
```

## Run

**Easiest (Windows):** double-click [`run.bat`](run.bat) in the project folder.

To **restart** after code changes (stops whatever is on port 8000, then starts fresh): double-click [`restart.bat`](restart.bat).

Or from PowerShell:

```powershell
.\run.ps1
```

Then open http://127.0.0.1:8000 in your browser.

**Important:** keep the terminal window open while you use the app. Closing it stops the server.

If the browser says "site can't be reached":
1. Check the terminal for red error text (Python/Node missing, port in use, etc.).
2. If `run.ps1` flashes and closes, use `run.bat` instead (handles execution policy).
3. Confirm nothing else is blocking port 8000, or that a previous server isn't already running.

Manual start (same as the script):

```bash
# from repo root
.venv\Scripts\python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

### Frontend dev mode (optional, hot reload)

```bash
# terminal 1: backend
.venv\Scripts\python -m uvicorn app.main:app --app-dir backend --port 8000
# terminal 2: vite dev server (proxies /api to :8000)
cd frontend && npm run dev   # http://localhost:5173
```

## Using the app

1. **Settings**: choose a provider and paste your own API key (stored only in a
   git-ignored local file `backend/data/config.json`; the backend makes the
   calls). Free-tier options:
   - **Gemini 2.5 Flash-Lite** (recommended): ~15 RPM / ~1,000 req/day, large
     context. Key at aistudio.google.com.
   - **Groq `llama-3.1-8b-instant`**: ~30 RPM / ~14,400 req/day, lower fidelity.
     Key at console.groq.com.
   - **OpenAI-compatible**: set a base URL + your own limits.
2. **Upload** a PDF guide, name the subject, and define tags (each card gets
   exactly one tag; a built-in `other` tag is always added).
3. **Review the tree** and edit it (rename / exclude / merge / delete) — nothing
   hits the AI yet.
4. **Approve** to start generation. Glossary/timeline cards appear immediately;
   body/caption cards stream in. If you hit the daily free quota, the job pauses
   and you can **Resume** later.
5. **Download** Text-Only or Master CSVs at any tier (subject / section /
   subheader). Click a node to **review and edit** its cards, or use the regen
   (↻) button to re-run a single node.

## Anki import

The CSV is plain 3-column `Front, Back, Tag`, UTF-8, fully quoted. In Anki:
File -> Import, set the field separator to **Comma**, map columns to
Front/Back/Tag, and enable **Allow HTML in fields** if your guide produced any
HTML. (Note: the third column is a plain data column, not Anki's native tags
field.)

## Tests

```bash
.venv\Scripts\python -m pytest backend/tests -q
```

Includes golden-file tests for the parser (the riskiest component) asserted
against the sample guide in `Guides/`.

## Building the Windows installer (distribution)

To give the app to someone else as a **Setup.exe** (no Python or Node required on their PC):

### Prerequisites (your build machine only)

- Python 3.11+ with project `.venv` and `backend/requirements.txt` installed
- Node.js 18+ (for `npm run build`)
- [Inno Setup 6](https://jrsoftware.org/isinfo.php) (free)

### Build

```powershell
.\packaging\build.ps1
```

Output: `packaging/output/AcDecFlashcards-Setup-0.1.0.exe`

Give recipients **only** the Setup.exe. Never include `tools/` or `tools/license_private_key.pem`.

### Recipient install

1. Run the Setup.exe and launch **AcDec Flashcard Generator** from the Start Menu.
2. Enter the product key you generate with `python tools/make_key.py --machine-id ...`.
3. User data (settings, database, uploads) is stored in `%LOCALAPPDATA%\AcDecFlashcards\`.

### Product keys

Licensed per machine for one year. Recipients send you their **Machine ID** from the license screen; you run:

```powershell
python tools/make_key.py --machine-id XXXX-XXXX-XXXX-XXXX --days 365
```

One-time keypair setup (owner only): `python tools/make_key.py --init`

## Notes / limitations

- Track B / Master decks contain figure **caption text**, not the images
  themselves (images aren't in the PDF text stream).
- Unlabeled captions (without a `FIGURE N` label) are best-effort.
- API keys are stored in plaintext locally and never committed.
```
