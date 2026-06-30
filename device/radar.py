"""newsbox 加速榜（异常注意力雷达）——找出提及异常加速的实体。

设计（2026-06-29 决策）：
- **双赛道**：上游 / 新闻分开计算，不再加权混合（上游 SNR 远高于新闻）
- **基线自适应**：EWMA z-score (α=0.15)，基线随长期变化自动跟随
  公式：μ_t = α·x_t + (1-α)·μ_{t-1}；σ²_t 同；z = (x_today - μ) / sqrt(σ² + ε)
- trend 数组：每实体最近 N 天的日计数（供前端 sparkline）

data要够厚：EWMA 在 2-3 周历史时收敛较稳，现阶段先打框架等data积累。
"""
from __future__ import annotations

import json
import math
from collections import defaultdict
from pathlib import Path

UPSTREAM = {"sec-edgar", "globenewswire", "prnewswire", "wallstreetcn", "wscn-astock", "dongcai-kx"}
DAY = 86400.0
DAYS = 14         # 历史窗口（天）
ALPHA = 0.15      # EWMA 系数（记忆约 6-7 天）
EPS = 0.5         # 方差兜底（避免初期 std=0 时除零）
MIN_TOTAL = 3     # 总提及阈值，低于此不进榜

# 来源样板词 / 交易所 / 通讯社 / 泛词 → 不是可交易实体, 过滤
_SKIP = {"Filer", "Filing", "Form", "Company", "Companies", "Inc", "Corp", "Ltd", "Limited",
         "Group", "Holdings", "Inc.", "Corp.", "Co.", "Ltd.", "Co", "Plc", "Board", "Board of Directors",
         "NYSE", "NASDAQ", "Nasdaq", "TSX", "TSXV", "OTC", "OTCQX", "OTCQB", "SEC", "EDGAR", "AMEX", "LSE", "MUNICH",
         "GLOBE NEWSWIRE", "GlobeNewswire", "PR Newswire", "PRNewswire", "Business Wire", "Newswire",
         "Reuters", "Bloomberg", "Intersolar", "Intersolar Europe", "AI", "API", "ETF",
         "央视", "新华社", "新华", "美军", "国务院", "记者", "公司", "集团", "本报",
         "新浪", "新浪财经", "新浪科技", "路透社", "路透", "彭博社", "彭博", "美联社", "法新社",
         "人民日报", "人民网", "环球时报", "中新社", "中国新闻网", "证券时报", "第一财经",
         "华尔街见闻", "财联社", "界面新闻", "澎湃新闻", "IT之家", "36氪", "中央社"}


def _skip(name: str) -> bool:
    if not name or name in _SKIP:
        return True
    c = name[0]
    if c.isascii() and c.isalpha() and c.islower():   # 英文首字母小写 = NER 噪声
        return True
    return False


def tier(src: str) -> str:
    return "up" if src in UPSTREAM else "news"


def load(path: Path) -> list[tuple[float, dict]]:
    rows = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            t = r.get("time")
            ts = float(t) if isinstance(t, (int, float)) else 0.0
            if ts < 1e9:
                continue
            rows.append((ts, r))
    return rows


def _ewma_zscore(series: list[int]) -> tuple[float, float]:
    """对日序列计算 EWMA z-score 与基线 μ。最后一项是今日，前面是历史。"""
    if len(series) < 2:
        return 0.0, 0.0
    mu = float(series[0])
    var = 0.0
    for x in series[1:-1]:
        d = x - mu
        mu += ALPHA * d
        var = (1 - ALPHA) * (var + ALPHA * d * d)
    today = series[-1]
    z = (today - mu) / math.sqrt(var + EPS)
    return z, mu


def compute_radar(rows: list[tuple[float, dict]], tier_filter: str | None = None) -> list[dict]:
    """tier_filter: 'up' 仅上游 / 'news' 仅新闻 / None 全部。返回按 z 降序的实体榜。"""
    if not rows:
        return []
    now = max(ts for ts, _ in rows)
    end_day = int(now // DAY)

    per = defaultdict(lambda: {
        "cnts": [0] * DAYS, "total": 0, "code": "", "ex": "",
        "today_up": 0, "heads": []
    })

    for ts, r in rows:
        is_up = tier(r.get("source", "")) == "up"
        if tier_filter == "up" and not is_up:
            continue
        if tier_filter == "news" and is_up:
            continue
        d = end_day - int(ts // DAY)
        if d < 0 or d >= DAYS:
            continue
        idx = DAYS - 1 - d            # 最近一天 = 末尾
        for e in r.get("entities", []):
            name = e.get("name")
            if _skip(name):
                continue
            s = per[name]
            s["cnts"][idx] += 1
            s["total"] += 1
            if e.get("code"):
                s["code"], s["ex"] = e["code"], e.get("exchange", "")
            if d == 0 and is_up:
                s["today_up"] += 1
            if d <= 1 and len(s["heads"]) < 5:
                s["heads"].append({"source": r.get("source", ""),
                                   "title": r.get("title", "")[:60], "up": is_up})

    out = []
    for name, s in per.items():
        if s["total"] < MIN_TOTAL:
            continue
        z, mu = _ewma_zscore(s["cnts"])
        today = s["cnts"][-1]
        if today == 0 or z <= 0:      # 加速榜：今日无提及或下降不入榜
            continue
        out.append({
            "name": name, "code": s["code"], "ex": s["ex"],
            "score": round(z, 2),
            "today": today, "today_up": s["today_up"],
            "baseline": round(mu, 2),
            "total": s["total"],
            "trend": s["cnts"],
            "heads": s["heads"],
        })
    out.sort(key=lambda x: -x["score"])
    return out


def main() -> None:
    import sys
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent / "store" / "analyzed.jsonl"
    rows = load(path)
    for label, tf in [("上游榜", "up"), ("新闻榜", "news")]:
        rad = [r for r in compute_radar(rows, tier_filter=tf) if r["code"]]
        print(f"\n=== {label}(可交易) top 10 ===")
        print(f"{'实体':<22}{'代码':<8}{'z':>6}{'今':>4}{'基线':>6}{'趋势 14d':>20}")
        for r in rad[:10]:
            tr = "".join("▁▂▃▄▅▆▇█"[min(7, c)] for c in r["trend"])
            print(f"{r['name'][:20]:<21}{r['code']:<8}{r['score']:>6}{r['today']:>4}{r['baseline']:>6}  {tr}")


if __name__ == "__main__":
    main()
