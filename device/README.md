# device（newsbox-nlp 部署核心）

原样移植到 Radxa Cubie A7A 的 NLP 分析核心。**保持干净**：只有 analyze.py 一个代码文件 + 数据 + 本说明，不放测试/实验。

## 结构
- `analyze.py` —— 全部逻辑：加载 JSONL → 实体 → 板块 → 事件 → 过滤 → 结构化输出
- `数据/` —— companies.csv / stopwords.txt / sectors.txt / events.txt（由lab生成/维护）
- `requirements.txt`

## 运行
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python analyze.py --data <新闻JSONL目录>
```

## 部署到板子（非烧录）
git clone / scp 整个 device 目录 → pip install -r requirements.txt → 跑。x86 与 aarch64 同一份代码。

> 设计与改进思路见 `../lab/notes.md`。
