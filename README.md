# newsbox-nlp

A financial-news NLP pipeline plus an **anomaly attention radar**. Ingests multi-source news
feeds, extracts structured entities/sectors/events, and surfaces the subjects whose mention
rate is suddenly accelerating — designed as an **information-advantage tool** for noticing
who's getting talked about more, not a price predictor. See
[`ROADMAP.md`](ROADMAP.md) for the full strategy and rationale.

## What it ingests
Out of the box, six **upstream** sources (filings / PR wires / live tickers, considered
the "leading" tier):
- **SEC EDGAR** (8-K filings, US company actions)
- **GlobeNewswire** / **PRNewswire** (corporate press wires)
- **Wallstreetcn** (Chinese live financial newswire, global + A-share channels)
- **Eastmoney live** (Chinese A-share fast news)

…plus a handful of **mainstream** feeds (lagging tier, for confirmation/context):
HackerNews, 36Kr, IT之家, Sina Finance, Sina Stock roll, Guardian (business/world/tech).

Each item is just a JSONL line — `{time, source, lang, title, url, summary}` — so adding a
new source means writing one parser and one URL.

## What it produces
For every news item, four structured fields:
- `entities` — companies / organizations, with stock code + exchange when a dictionary
  match is found (combined spaCy NER + substring match against an A-share + US-ticker
  dictionary; ~16k tickers built by `lab/build_dict.py`)
- `sectors` — controlled vocabulary of industry / theme tags
- `events` — controlled vocabulary of event types (financing, IPO, earnings, M&A,
  regulation, …)
- `keywords` — residual high-signal terms after stopword + POS filtering

On top of that, **`radar.py`** computes an EWMA z-score per entity per day, in two separate
tracks (upstream vs. news), and ranks subjects whose recent mentions are accelerating
against their own baseline.

## Project layout
```
newsbox-nlp/
├── start.bat          One-click launcher (Windows + WSL)
├── ROADMAP.md         Strategy, decisions, open questions
├── device/            Analysis core (portable to any Linux/SBC: pip install + run)
│   ├── main.py         pipeline: pull → analyze → store
│   ├── analyze.py      NLP: dictionary + spaCy NER + sectors/events
│   ├── radar.py        Acceleration ranking (EWMA z-score, dual track)
│   ├── data/           Dictionaries (companies.csv, stopwords, sectors, events)
│   └── store/          analyzed.jsonl  (gitignored runtime output)
├── lab/               NLP improvement workbench (not deployed)
│   ├── build_dict.py   Pull A-share + US tickers → data/companies.csv
│   ├── eval.py         Coverage / quality eval
│   └── notes.md
└── panel/             Web frontend + backend
    ├── server.py       FastAPI (SQLite + REST + page server)
    └── dashboard.html  Single-file UI (Chart.js, vanilla JS)
```

## Setup
Prerequisites: **Windows 10/11 with WSL2 Ubuntu** (or any Linux), Python 3.10+, ~6 GB free disk
(spaCy + transformers + jieba).

```bash
# In WSL (Linux side), from project root:
python3 -m venv .venv
source .venv/bin/activate
pip install -r device/requirements.txt
python -m spacy download zh_core_web_sm
python -m spacy download en_core_web_sm

# Build the company dictionary (A-share + US tickers). Needs internet.
python lab/build_dict.py
```

## Raw data
Place the device's collected news under `<project_root>/data/`, structured as:
```
data/
├── news/{cn,en}/YYYY-MM-DD.jsonl
└── upstream/{cn,en}/YYYY-MM-DD.jsonl
```
Each JSONL line: `{"time": <unix_sec>, "source": "...", "lang": "cn|en", "title": "...", ...}`

Override the location with the `NEWSBOX_RAW_DIR` environment variable.

## Run
```cmd
:: Windows: double-click start.bat
start.bat
```
Or manually:
```bash
# Backend (auto-reanalyzes if data is newer than analyzed.jsonl)
.venv/bin/python panel/server.py
# → http://localhost:8000
```

## How it works
1. `device/main.py` reads raw JSONL (via `--from-file <data_dir>`, or pulled over WiFi/USB
   from an external collector — see `fetch_from_board` / `fetch_from_usb`)
   → runs `analyze.py` → appends to `device/store/analyzed.jsonl`.
2. `panel/server.py` on startup checks if raw data is newer than the analyzed cache; if so,
   re-runs the analysis. Builds a SQLite index for fast API queries.
3. The dashboard hits `/api/radar?tier=up|news` for the acceleration ranking, `/api/companies`
   for total mentions, `/api/tag` for drill-down to all source news of any tag.

## License
Personal project, no license declared yet.
