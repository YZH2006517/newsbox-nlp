"""评估改进版 analyze.py 的抽取质量(lab工具, 不上板)。

用法: python eval.py [analyzed.jsonl]
  - 不带参数: 跑内置 A股例句 + 读 ../device/store/analyzed.jsonl 统计覆盖率
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "device"))
import analyze  # noqa: E402


def show_cn_examples() -> None:
    tests = [
        {"lang": "cn", "title": "宁德时代发布半年报，动力电池出货量大增", "summary": "宁德时代上半年净利润同比增长，光伏与储能业务扩张。"},
        {"lang": "cn", "title": "贵州茅台拟回购股份，比亚迪新能源车交付创新高", "summary": "贵州茅台公告回购，比亚迪汽车销量增长。"},
        {"lang": "cn", "title": "中芯国际获大基金增持，半导体设备国产替代加速", "summary": "中芯国际晶圆扩产，芯片产业链受关注。"},
    ]
    print("==== A股例句(验证中文词典) ====")
    for t in tests:
        r = analyze.analyze(t)
        print("·", t["title"][:30])
        print("   实体:", [f'{e["name"]}({e["code"]})' for e in r["entities"]],
              "| 板块:", r["sectors"], "| 事件:", r["events"], "| 关键词:", r["keywords"])


def stats(path: Path) -> None:
    if not path.exists():
        print(f"\n(无 {path}, 先 main.py 跑一遍)")
        return
    rows = [json.loads(l) for l in open(path, encoding="utf-8")]
    ne = sum(1 for r in rows if r["entities"])
    print(f"\n==== {path.name}: {len(rows)} 条 ====")
    print(f"命中实体 {ne} | 板块 {sum(1 for r in rows if r['sectors'])} | 事件 {sum(1 for r in rows if r['events'])}")
    print("有公司实体的samples:")
    shown = 0
    for r in rows:
        if r["entities"]:
            print("  ·", r["title"][:34], "→", [e["name"] for e in r["entities"]],
                  r["sectors"], r["events"])
            shown += 1
            if shown >= 8:
                break


if __name__ == "__main__":
    show_cn_examples()
    p = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "device" / "store" / "analyzed.jsonl"
    stats(p)
