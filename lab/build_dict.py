"""下载 A股 + 美股公司名 → device/data/companies.csv(改进 NLP 的词典原料)。

依赖(仅lab用, 不进device requirements):
    pip install akshare        # A股列表
    requests                   # 美股走 SEC 官方 JSON, 免 key

列: code,name,alias,industry,exchange
    code=代码(A股6位 / 美股ticker)  name=名称  alias=别名(;分隔, 先留空后续补)
    industry=行业(先留空)  exchange=SH/SZ/BJ/US

用法: python build_dict.py   →  写 ../device/data/companies.csv
"""
import csv
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "device" / "data" / "companies.csv"


def a_shares() -> list[dict]:
    import akshare as ak
    df = ak.stock_info_a_code_name()      # 列: code, name
    rows = []
    for _, r in df.iterrows():
        code = str(r["code"]).zfill(6)
        ex = "SH" if code[0] in "69" else "BJ" if code[0] in "48" else "SZ"
        rows.append({"code": code, "name": str(r["name"]).strip(),
                     "alias": "", "industry": "", "exchange": ex})
    return rows


def us_stocks() -> list[dict]:
    import requests
    url = "https://www.sec.gov/files/company_tickers.json"
    j = requests.get(url, headers={"User-Agent": "newsbox-nlp dev contact@example.com"}, timeout=30).json()
    rows = []
    for v in j.values():
        name = str(v.get("title", "")).strip()
        tic = str(v.get("ticker", "")).strip()
        if name and tic:
            rows.append({"code": tic, "name": name, "alias": "", "industry": "", "exchange": "US"})
    return rows


def main() -> None:
    rows: list[dict] = []
    try:
        a = a_shares(); rows += a; print(f"A股 {len(a)} 家")
    except Exception as e:
        print("A股下载失败:", e)
    try:
        u = us_stocks(); rows += u; print(f"美股 {len(u)} 家")
    except Exception as e:
        print("美股下载失败:", e)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["code", "name", "alias", "industry", "exchange"])
        w.writeheader()
        w.writerows(rows)
    print(f"共 {len(rows)} 家 → {OUT}")


if __name__ == "__main__":
    main()
