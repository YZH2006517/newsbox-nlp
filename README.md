# newsbox-nlp

Anomaly attention radar for financial news. Collects news + upstream (SEC / PR / live wires) on
an ESP32-S3 device, analyzes on PC/SBC, surfaces entities whose mention rate suddenly
accelerates — designed as an **information advantage tool**, not a price predictor. See
[`ROADMAP.md`](ROADMAP.md) for the full strategy and rationale.

## Project layout
```
newsbox-nlp/
├── start.bat          One-click launcher (Windows + WSL)
├── ROADMAP.md         Strategy, decisions, open questions
├── device/            Analysis core — designed to run on the SBC (Cubie A7A) later
│   ├── main.py         pipeline: pull → analyze → store
│   ├── analyze.py      NLP: dictionary + spaCy NER + sectors/events
│   ├── radar.py        Acceleration ranking (EWMA z-score, dual track)
│   ├── data/           Dictionaries (companies.csv, stopwords, sectors, events)
│   └── store/          analyzed.jsonl  (gitignored runtime output)
├── lab/               NLP improvement workbench (not deployed to device)
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
1. `device/main.py` reads raw JSONL (from `--from-file <data_dir>` or pulled from the ESP32 device)
   → runs `analyze.py` → appends to `device/store/analyzed.jsonl`.
2. `panel/server.py` on startup checks if raw data is newer than the analyzed cache; if so,
   re-runs the analysis. Builds a SQLite index for fast API queries.
3. The dashboard hits `/api/radar?tier=up|news` for the acceleration ranking, `/api/companies`
   for total mentions, `/api/tag` for drill-down to all source news of any tag.

## License
Personal project, no license declared yet.
