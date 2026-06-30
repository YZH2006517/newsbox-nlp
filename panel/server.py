"""newsbox panel后端：读 device/store/analyzed.jsonl → SQLite → REST API + 提供 dashboard.html。

独立运行(暂不并入device, 后期移植)。依赖: fastapi, uvicorn。
跑: python server.py   (0.0.0.0:8000, 局域网可访问)

data流: analyzed.jsonl(每条带 entities/sectors/events/keywords) → news + tags 两表 → SQL 聚合。
所有列表/下钻均无条数上限; 每个标签都能点开看其全部来源新闻(/api/tag)。
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

HERE = Path(__file__).resolve().parent
JSONL = HERE.parent / "device" / "store" / "analyzed.jsonl"
DB = HERE / "newsbox.db"

import sys as _sys
_sys.path.insert(0, str(HERE.parent / "device"))
try:
    import radar as _radar
    _skip_entity = _radar._skip
except Exception:
    def _skip_entity(name):   # radar 不可用时不过滤
        return False


def _date(t) -> str:
    try:
        if isinstance(t, (int, float)):
            return datetime.fromtimestamp(float(t)).strftime("%Y-%m-%d")
        return datetime.fromisoformat(str(t)).strftime("%Y-%m-%d")
    except (ValueError, OSError):
        return ""


def _ts(t) -> int:
    if isinstance(t, (int, float)):
        return int(t)
    try:
        return int(datetime.fromisoformat(str(t)).timestamp())
    except ValueError:
        return 0


def build_db() -> int:
    con = sqlite3.connect(DB)
    con.executescript("""
        DROP TABLE IF EXISTS news; DROP TABLE IF EXISTS tags;
        CREATE TABLE news(id INTEGER PRIMARY KEY, ts INT, date TEXT, source TEXT,
                          lang TEXT, title TEXT, url TEXT);
        CREATE TABLE tags(news_id INT, kind TEXT, value TEXT, code TEXT, ex TEXT);
        CREATE INDEX ix_tag ON tags(kind, value);
        CREATE INDEX ix_tag_news ON tags(news_id);
        CREATE INDEX ix_news_ts ON news(ts);
    """)
    n = 0
    if JSONL.exists():
        with open(JSONL, encoding="utf-8") as fh:
            for i, line in enumerate(fh):
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                t = r.get("time")
                con.execute("INSERT INTO news(id,ts,date,source,lang,title,url) VALUES(?,?,?,?,?,?,?)",
                            (i, _ts(t), _date(t), r.get("source", ""), r.get("lang", ""),
                             r.get("title", ""), r.get("url", "")))
                for e in r.get("entities", []):
                    name = e.get("name", "")
                    if _skip_entity(name):   # 剔除来源名/样板词(Filer/NYSE/新浪/央视…)
                        continue
                    con.execute("INSERT INTO tags VALUES(?,?,?,?,?)",
                                (i, "entity", name, e.get("code", ""), e.get("exchange", "")))
                for s in r.get("sectors", []):
                    con.execute("INSERT INTO tags VALUES(?,?,?,?,?)", (i, "sector", s, "", ""))
                for ev in r.get("events", []):
                    con.execute("INSERT INTO tags VALUES(?,?,?,?,?)", (i, "event", ev, "", ""))
                for kw in r.get("keywords", [])[:4]:
                    con.execute("INSERT INTO tags VALUES(?,?,?,?,?)", (i, "keyword", kw, "", ""))
                n += 1
    con.commit()
    con.close()
    return n


def q(sql: str, args=()) -> list[dict]:
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    rows = [dict(x) for x in con.execute(sql, args).fetchall()]
    con.close()
    return rows


def _recent_dates(k: int = 7) -> list[str]:
    rows = q("SELECT DISTINCT date FROM news WHERE date<>'' AND date>'1971' ORDER BY date DESC LIMIT ?", (k,))
    return [r["date"] for r in rows][::-1]


def _series(value: str, kind: str, dates: list[str]) -> list[int]:
    m = {r["date"]: r["c"] for r in q(
        "SELECT n.date, count(DISTINCT n.id) c FROM tags t JOIN news n ON n.id=t.news_id "
        "WHERE t.kind=? AND t.value=? GROUP BY n.date", (kind, value))}
    return [m.get(d, 0) for d in dates]


app = FastAPI(title="newsbox panel")


@app.get("/api/overview")
def overview():
    dates = _recent_dates(7)
    dc = {r["date"]: r["c"] for r in q("SELECT date,count(*) c FROM news GROUP BY date")}
    vol = [{"date": d, "c": dc.get(d, 0)} for d in dates]
    return {
        "total": q("SELECT count(*) c FROM news")[0]["c"],
        "today": vol[-1]["c"] if vol else 0,
        "ncomp": q("SELECT count(DISTINCT value) c FROM tags WHERE kind='entity'")[0]["c"],
        "nsec": q("SELECT count(DISTINCT value) c FROM tags WHERE kind='sector'")[0]["c"],
        "vol": vol,
        "hot": q("SELECT value name, code, ex, count(DISTINCT news_id) c FROM tags WHERE kind='entity' "
                 "GROUP BY value ORDER BY c DESC"),
    }


@app.get("/api/companies")
def companies():
    """公司榜：总热度（累计提及）。折线趋势已移到加速榜。"""
    return {"rank": q("SELECT value name, code, ex, count(DISTINCT news_id) c FROM tags WHERE kind='entity' "
                      "GROUP BY value ORDER BY c DESC")}


@app.get("/api/sectors")
def sectors():
    return {"rank": q("SELECT value name, count(DISTINCT news_id) c FROM tags WHERE kind='sector' "
                      "GROUP BY value ORDER BY c DESC")}


@app.get("/api/events")
def events():
    return {"rank": q("SELECT value name, count(DISTINCT news_id) c FROM tags WHERE kind='event' "
                      "GROUP BY value ORDER BY c DESC")}


@app.get("/api/tag")
def tag(kind: str, value: str):
    """通用下钻: 某标签的全部来源新闻 + 趋势(无上限)。kind ∈ entity/sector/event/keyword。"""
    dates = _recent_dates(7)
    total = q("SELECT count(DISTINCT news_id) c FROM tags WHERE kind=? AND value=?", (kind, value))[0]["c"]
    news = q("SELECT DISTINCT n.id, n.title, n.source, n.url, n.ts, n.lang FROM tags t "
             "JOIN news n ON n.id=t.news_id WHERE t.kind=? AND t.value=? ORDER BY n.ts DESC", (kind, value))
    res = {"kind": kind, "value": value, "count": total, "dates": dates,
           "trend": _series(value, kind, dates), "news": news}
    if kind == "entity":
        info = q("SELECT code, ex FROM tags WHERE kind='entity' AND value=? AND code<>'' LIMIT 1", (value,))
        res["code"] = info[0]["code"] if info else ""
        res["ex"] = info[0]["ex"] if info else ""
        res["sectors"] = [s["v"] for s in q(
            "SELECT t2.value v, count(*) c FROM tags t JOIN tags t2 ON t.news_id=t2.news_id "
            "WHERE t.kind='entity' AND t.value=? AND t2.kind='sector' GROUP BY t2.value ORDER BY c DESC", (value,))]
        res["events"] = [e["v"] for e in q(
            "SELECT t2.value v, count(*) c FROM tags t JOIN tags t2 ON t.news_id=t2.news_id "
            "WHERE t.kind='entity' AND t.value=? AND t2.kind='event' GROUP BY t2.value ORDER BY c DESC", (value,))]
    return res


@app.get("/api/feed")
def feed(lang: str = "", limit: int = 10000):
    where = "WHERE lang=?" if lang in ("cn", "en") else ""
    args = (lang, limit) if where else (limit,)
    rows = q(f"SELECT id, ts, source, lang, title, url FROM news {where} ORDER BY ts DESC LIMIT ?", args)
    ids = [r["id"] for r in rows]
    tagmap: dict[int, list] = {i: [] for i in ids}
    if ids:
        ph = ",".join("?" * len(ids))
        for t in q(f"SELECT news_id, kind, value FROM tags WHERE news_id IN ({ph})", ids):
            tagmap[t["news_id"]].append({"kind": t["kind"], "value": t["value"]})
    for r in rows:
        r["tags"] = tagmap.get(r["id"], [])
    return {"items": rows, "total": q("SELECT count(*) c FROM news")[0]["c"]}


@app.get("/api/radar")
def radar_api(coded: int = 0, tier: str = "up"):
    """加速榜: tier='up' 仅上游(默认) / 'news' 仅新闻 / 'all' 全部。"""
    import sys
    sys.path.insert(0, str(HERE.parent / "device"))
    import radar
    tf = tier if tier in ("up", "news") else None
    rad = radar.compute_radar(radar.load(JSONL), tier_filter=tf)
    if coded:
        rad = [r for r in rad if r["code"]]
    return {"items": rad, "total": len(rad), "tier": tier}


# Raw news data directory. Default: <project_root>/data
# Override via env: NEWSBOX_RAW_DIR=/path/to/data
import os as _os
RAW_DIR = Path(_os.environ.get("NEWSBOX_RAW_DIR", str(HERE.parent / "data")))


@app.post("/api/rebuild")
def rebuild():
    """完整流水线: 用 RAW_DIR 最新数据重新分析 → 重建 SQLite。
    若 raw 比 analyzed.jsonl 新, 自动重分析(耗时几分钟); 否则只重建 SQLite(秒级)。"""
    import subprocess
    need_reanalyze = False
    if RAW_DIR.exists():
        if not JSONL.exists():
            need_reanalyze = True
        else:
            raw_mtime = max((f.stat().st_mtime for f in RAW_DIR.rglob("*.jsonl")), default=0)
            if raw_mtime > JSONL.stat().st_mtime:
                need_reanalyze = True
    if need_reanalyze:
        if JSONL.exists():
            JSONL.unlink()
        python = str(HERE.parent / ".venv" / "bin" / "python")
        main_py = str(HERE.parent / "device" / "main.py")
        proc = subprocess.run(
            [python, main_py, "--from-file", str(RAW_DIR), "--store", str(JSONL.parent)],
            capture_output=True, text=True, timeout=900
        )
        if proc.returncode != 0 or not JSONL.exists():
            return {"error": "重分析失败",
                    "stderr": (proc.stderr or "")[-500:],
                    "stdout": (proc.stdout or "")[-500:]}
        return {"loaded": build_db(), "reanalyzed": True, "log": proc.stdout[-200:]}
    return {"loaded": build_db(), "reanalyzed": False}


@app.get("/")
def index():
    return HTMLResponse((HERE / "dashboard.html").read_text(encoding="utf-8"))


def _ensure_analyzed():
    """启动前: 若 analyzed.jsonl 丢失或比 raw 旧, 自动跑分析(首次/数据更新场景)。"""
    import subprocess
    if not RAW_DIR.exists():
        return
    need = False
    if not JSONL.exists():
        need = True
        print(f"analyzed.jsonl 不存在, 用 {RAW_DIR} 跑首次分析(NER 较慢, 几分钟)…")
    else:
        raw_m = max((f.stat().st_mtime for f in RAW_DIR.rglob("*.jsonl")), default=0)
        if raw_m > JSONL.stat().st_mtime:
            need = True
            print(f"原始数据有更新, 重新分析…")
    if need:
        if JSONL.exists():
            JSONL.unlink()
        python = str(HERE.parent / ".venv" / "bin" / "python")
        main_py = str(HERE.parent / "device" / "main.py")
        proc = subprocess.run(
            [python, main_py, "--from-file", str(RAW_DIR), "--store", str(JSONL.parent)],
            timeout=1200
        )
        if proc.returncode != 0 or not JSONL.exists():
            print(f"分析失败(returncode={proc.returncode}), 请手动 cd device && python main.py --from-file {RAW_DIR}")


if __name__ == "__main__":
    import uvicorn
    _ensure_analyzed()
    print(f"载入 {build_db()} 条 → {DB}")
    uvicorn.run(app, host="0.0.0.0", port=8000)
