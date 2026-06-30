"""newsbox-nlp 分析核心（NER 驱动 + 词典增强）。

外围 main.py 只调用 analyze(item)。换 NLP 只改本文件。

  2 NER(主)  : spaCy 抓 ORG 实体——不依赖名单, 覆盖华为/字节/OpenAI 等未上市公司、
               多词名、人名机构; "机器人"作普通名词不会被判成公司(精度).
  1 词典(增强): 实体命中 data/companies.csv → 补股票代码/交易所.
  3 受控     : data/sectors.txt 板块、data/events.txt 事件, 命中即标签.
  4 过滤     : data/stopwords.txt + jieba 词性 → 有区分度的关键词.

输出四栏 entities(谁) / sectors / events / keywords。spaCy 缺失时退化为纯词典(仅高置信匹配)。
"""
from __future__ import annotations

import csv
import html
import re
from pathlib import Path

import jieba
import jieba.analyse

_DATA = Path(__file__).resolve().parent / "data"
_TAG = re.compile(r"<[^>]+>")
_US_SUFFIX = re.compile(r"[,.]| Inc\b| Corp\b| Corporation\b| Co\b| Company\b| Ltd\b|"
                        r" Holdings\b| Group\b| PLC\b| LP\b| LLC\b| NV\b| SA\b| AG\b", re.I)


def _clean(t: str) -> str:
    t = _TAG.sub(" ", html.unescape(t or ""))
    return re.sub(r"\s+", " ", t).strip()


# ---------- 词典（增强：实体→股票代码） ----------
_cn_company: dict[str, dict] = {}
_cn_names_long: list[str] = []   # 长度≥3 的 A股公司名, 长名优先(substring 匹配)
_us_core: dict[str, str] = {}
_us_ticker: dict[str, str] = {}


def _load_companies() -> None:
    f = _DATA / "companies.csv"
    if not f.exists():
        return
    with open(f, encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            name = (r.get("name") or "").strip()
            code = (r.get("code") or "").strip()
            ex = (r.get("exchange") or "").strip()
            if not name:
                continue
            if ex == "US":
                if code:
                    _us_ticker[code.upper()] = name
                core = _US_SUFFIX.split(name)[0].strip()
                if len(core) >= 3:
                    _us_core.setdefault(core.lower(), code)
            elif len(name) >= 2:
                _cn_company[name] = {"code": code, "exchange": ex}
    # 长度≥3、不在歧义黑名单的 A股名按长度倒序, 用于 substring 匹配(长名优先)
    _cn_names_long[:] = sorted((n for n in _cn_company if len(n) >= 3), key=len, reverse=True)


def _enrich(name: str, lang: str) -> dict | None:
    """实体名 → 股票代码/交易所(命中词典才有, 未上市返回 None)。"""
    if lang == "cn":
        return _cn_company.get(name)
    up = name.upper()
    if up in _us_ticker:
        return {"code": up, "exchange": "US"}
    core = _US_SUFFIX.split(name)[0].strip().lower()
    if core in _us_core:
        return {"code": _us_core[core], "exchange": "US"}
    return None


def _load_lines(fname: str) -> list[str]:
    f = _DATA / fname
    if not f.exists():
        return []
    return [x.strip() for x in f.read_text(encoding="utf-8").splitlines()
            if x.strip() and not x.startswith("#")]


_load_companies()
_STOP = set(_load_lines("stopwords.txt"))
_SECTORS = _load_lines("sectors.txt")
_EVENTS = _load_lines("events.txt")
_EN_STOP = {"the", "a", "an", "of", "to", "in", "on", "and", "for", "as", "at", "with", "by",
            "is", "are", "from", "into", "over", "after", "its", "has", "that", "this", "will",
            "new", "says", "say", "amid", "but", "not", "you", "your", "how", "what", "why"}
# 既是常见词/板块、又恰好是 A股名 → 不当公司(避免"机器人"误报)
_CN_AMBIG = set(_SECTORS) | {"新产业", "中国", "国际", "时代", "科技", "信息", "软件", "data",
                             "网络", "智能", "通信", "电子", "世纪", "东方", "未来", "旗下", "概念"}
# 常见缩写: 别当成大写 ticker
_TICKER_STOP = {"SSL", "DNS", "API", "CEO", "CFO", "CTO", "CPU", "GPU", "RAM", "USB", "URL", "SDK",
                "FAQ", "PDF", "GTA", "HTTP", "HTML", "JSON", "SQL", "AWS", "IOS", "IPO", "ETF",
                "GDP", "FBI", "NASA", "LLM", "NPU", "RSS", "XML", "CSS", "NFT", "VPN", "GEO", "HN"}
# NER 把这些地名/术语缩写误当机构 → 过滤
_NER_STOP = _TICKER_STOP | {"EU", "US", "UK", "UN", "AI", "ML", "AR", "VR", "IT", "PC", "OS",
                            "TV", "5G", "4G", "Q1", "Q2", "Q3", "Q4", "GenAI", "SaaS", "iOS"}


# ---------- spaCy NER（主检测） ----------
_nlp: dict[str, object] = {}


def _doc(text: str, lang: str):
    try:
        import spacy
    except ImportError:
        return None
    if lang not in _nlp:
        model = "zh_core_web_sm" if lang == "cn" else "en_core_web_sm"
        try:
            _nlp[lang] = spacy.load(model, disable=["parser", "lemmatizer"])
        except Exception:
            _nlp[lang] = None
    nlp = _nlp[lang]
    return nlp(text[:1500]) if nlp else None


def _entities(text: str, lang: str) -> list[dict]:
    """混合: NER 抓 ORG(含未上市/多词/英文公司) + 词典补(中文 A股召回主力)。"""
    out: list[dict] = []
    seen: set[str] = set()

    def add(name: str, info: dict | None = None) -> None:
        if not name or name in seen:
            return
        seen.add(name)
        e = {"name": name, "type": "ORG"}
        if info:
            e.update(info)
        out.append(e)

    doc = _doc(text, lang)            # 1) NER ORG 跨度
    if doc is not None:
        for ent in doc.ents:
            if ent.label_ != "ORG":
                continue
            name = ent.text.strip(" 　,.，。、:：\"'`")
            if len(name) < 2 or name in _STOP or name in _SECTORS or name in _NER_STOP:
                continue
            if name.isupper() and len(name) <= 2:   # 纯大写双字母多为缩写
                continue
            add(name, _enrich(name, lang))

    if lang == "cn":                 # 2) 中文 A股: substring 匹配(长名优先, 不重叠)
        used = [False] * len(text)   # 同一段文本不被多个公司名重复占用
        for name in _cn_names_long:
            if name in _CN_AMBIG:
                continue
            start = 0
            while True:
                pos = text.find(name, start)
                if pos < 0:
                    break
                end = pos + len(name)
                if any(used[k] for k in range(pos, end)):
                    start = pos + 1
                    continue
                add(name, _cn_company[name])
                for k in range(pos, end):
                    used[k] = True
                start = end
    else:
        for w in re.findall(r"[A-Z][A-Za-z.&]{2,}", text):
            if w.isupper() and w in _us_ticker and w not in _TICKER_STOP:
                add(_us_ticker[w], {"code": w, "exchange": "US"})
    return out


def _match(text: str, vocab: list[str]) -> list[str]:
    return [v for v in vocab if v in text]


def _keywords(text: str, lang: str, drop: set[str], topk: int = 5) -> list[str]:
    if lang == "cn":
        cand = jieba.analyse.textrank(text, topK=topk + 10,
                                      allowPOS=("n", "nz", "nt", "nr", "ns", "vn"))
        return [w for w in cand if w not in _STOP and w not in drop and len(w) >= 2][:topk]
    freq: dict[str, int] = {}
    for w in re.findall(r"[A-Za-z][A-Za-z\-]+", text):
        lo = w.lower()
        if len(lo) > 3 and lo not in _EN_STOP and lo not in drop:
            freq[lo] = freq.get(lo, 0) + 1
    return [w for w, _ in sorted(freq.items(), key=lambda x: -x[1])[:topk]]


def analyze(item: dict) -> dict:
    lang = item.get("lang", "")
    text = _clean(item.get("title", "") + " " + item.get("summary", ""))
    entities = _entities(text, lang)
    sectors = _match(text, _SECTORS)
    events = _match(text, _EVENTS)
    drop = set(sectors) | set(events) | {e["name"] for e in entities}
    drop |= {e["name"].lower() for e in entities}
    return {
        "time": item.get("time", ""),
        "source": item.get("source", ""),
        "lang": lang,
        "title": item.get("title", ""),
        "url": item.get("url", ""),
        "entities": entities,
        "sectors": sectors,
        "events": events,
        "keywords": _keywords(text, lang, drop),
    }
