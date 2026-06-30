"""newsbox-nlp 外围主程序（拉取 → 存档 → 分析 → 落盘）。

data来源（三选一，互斥）：
  --usb   <端口>      经 USB 线连板子，发 "SINCE <ts>" 拉取（Linux: /dev/ttyACM0，Windows: COM5）
  --board <host:port> 经 WiFi 连板子 P2，GET /news?since=<ts>
  --from-file <jsonl> 用本地 JSONL（板子未就绪时跑通外围）

维护游标(cursor)做增量拉取；原始新闻与分析结果分别落盘。
NLP 逻辑全在 analyze.py，本文件不含分析逻辑——以后换 NLP 不动这里。
各依赖按需加载：requests 仅 WiFi 用，pyserial 仅 USB 用，jieba 仅分析用。

用法：
    python main.py --usb /dev/ttyACM0                 # USB 直连（Cubie 上）
    python main.py --board 192.168.5.44:80            # WiFi 增量拉取
    python main.py --board 192.168.5.44:80 --loop --interval 300
    python main.py --from-file ../lab/samples/cn.jsonl # 本地samples跑通外围
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime
from pathlib import Path


def _item_ts(item: dict) -> float:
    """取新闻 time → unix 秒。板子用数字(unix秒)，samples用 ISO 字符串，两者都支持。"""
    t = item.get("time")
    if isinstance(t, (int, float)):
        return float(t)
    if isinstance(t, str):
        try:
            return datetime.fromisoformat(t).timestamp()
        except ValueError:
            try:
                return float(t)
            except ValueError:
                return 0.0
    return 0.0


def _load_cursor(store: Path) -> float:
    f = store / "cursor.txt"
    if f.exists():
        try:
            return float(f.read_text().strip())
        except ValueError:
            return 0.0
    return 0.0


def _save_cursor(store: Path, ts: float) -> None:
    (store / "cursor.txt").write_text(str(ts))


def _append_jsonl(path: Path, obj: dict) -> None:
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(obj, ensure_ascii=False) + "\n")


def _parse_jsonl(text: str) -> list[dict]:
    items = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            items.append(json.loads(line))
        except json.JSONDecodeError:
            pass  # 跳过半行/损坏行（板子断电可能写半行）
    return items


def fetch_from_board(board: str, since: float, timeout: int = 40) -> list[dict] | None:
    """WiFi：GET /news?since=。板子离线/出错返回 None（与"拉到0条"区分）。"""
    import requests
    url = f"http://{board}/news?since={int(since)}"
    try:
        r = requests.get(url, timeout=timeout)
        r.raise_for_status()
        return _parse_jsonl(r.text)
    except requests.RequestException as e:
        print(f"[WiFi] 拉取失败 {url} -> {e}")
        return None


def fetch_from_usb(port: str, since: float, retries: int = 8) -> list[dict] | None:
    """USB：发 'SINCE <ts>'，解析 <<<NEWS BEGIN>>>..{json}..<<<NEWS END>>> 帧。
    板子抓取中回 BUSY 自动重试；只取 BEGIN/END 之间以 '{' 开头的行（跳过夹杂日志）。
    打不开串口返回 None。"""
    try:
        import serial
    except ImportError:
        print("[USB] 缺少 pyserial：pip install pyserial")
        return None
    try:
        s = serial.Serial(port, 115200, timeout=0.3)
    except Exception as e:
        print(f"[USB] 打开 {port} 失败：{e}")
        return None
    try:
        time.sleep(0.3); s.reset_input_buffer()
        for attempt in range(1, retries + 1):
            s.reset_input_buffer()
            s.write(f"SINCE {int(since)}\n".encode()); s.flush()
            items, in_block, busy, ended = [], False, False, False
            t0 = time.time()
            while time.time() - t0 < 30:
                raw = s.readline()
                if not raw:
                    continue
                ln = raw.decode("utf-8", "replace").rstrip("\r\n")
                if "NEWS BUSY" in ln:
                    busy = True; break
                if "NEWS BEGIN" in ln:
                    in_block = True; continue
                if "NEWS END" in ln:
                    ended = True; break
                if in_block and ln.startswith("{"):
                    try:
                        items.append(json.loads(ln))
                    except json.JSONDecodeError:
                        pass
            if ended:
                return items
            if busy:
                print(f"[USB] 板子抓取中，{attempt}/{retries} 重试"); time.sleep(3); continue
            print(f"[USB] 无响应，{attempt}/{retries} 重试"); time.sleep(1)
        return None
    finally:
        s.close()


def process(items: list[dict], store: Path) -> float:
    """跑分析落盘，返回本批最大时间游标。(原始data已在源端 SD, 不再备份)"""
    import analyze as nlp
    out_f = store / "analyzed.jsonl"
    max_ts = 0.0
    for it in items:
        _append_jsonl(out_f, nlp.analyze(it))
        max_ts = max(max_ts, _item_ts(it))
    return max_ts


def run_once(args, store: Path) -> None:
    if args.from_file:
        p = Path(args.from_file)
        rd = lambda f: f.read_text(encoding="utf-8", errors="replace")   # 板子可能截断多字节 → 容错
        if p.is_dir():   # 传目录(如板子 /news): 读其下所有 *.jsonl
            text = "\n".join(rd(f) for f in sorted(p.rglob("*.jsonl")))
        else:
            text = rd(p)
        items = _parse_jsonl(text)
        print(f"[本地] 读入 {len(items)} 条：{args.from_file}")
    else:
        cursor = args.since if args.since is not None else _load_cursor(store)
        if args.usb:
            items = fetch_from_usb(args.usb, cursor)
            src = f"USB {args.usb}"
        else:
            items = fetch_from_board(args.board, cursor)
            src = f"WiFi {args.board}"
        if items is None:
            return  # 离线，保留游标下次再拉
        print(f"[{src}] since={cursor:.0f} 拉到 {len(items)} 条")

    if not items:
        return
    max_ts = process(items, store)
    if not args.from_file and max_ts > 0:
        _save_cursor(store, max_ts)
    print(f"[完成] 已分析 {len(items)} 条 -> {store/'analyzed.jsonl'}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--usb", help="USB 串口，如 /dev/ttyACM0 或 COM5")
    ap.add_argument("--board", help="WiFi 板子地址 host:port，如 192.168.5.44:80")
    ap.add_argument("--from-file", help="改用本地 JSONL（板子未就绪时测试外围）")
    ap.add_argument("--store", default="store", help="本地存档目录")
    ap.add_argument("--since", type=float, help="覆盖游标，从该 unix 秒开始拉")
    ap.add_argument("--loop", action="store_true", help="常驻轮询")
    ap.add_argument("--interval", type=int, default=300, help="轮询间隔秒")
    args = ap.parse_args()

    if not (args.usb or args.board or args.from_file):
        ap.error("需指定 --usb / --board / --from-file 其一")

    store = Path(args.store)
    store.mkdir(parents=True, exist_ok=True)

    if args.loop and not args.from_file:
        print(f"[常驻] 每 {args.interval}s 拉取一次")
        while True:
            run_once(args, store)
            time.sleep(args.interval)
    else:
        run_once(args, store)


if __name__ == "__main__":
    main()
