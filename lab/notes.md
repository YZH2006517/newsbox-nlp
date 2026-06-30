# newsbox-nlp 规划（lab记录）

电脑/SBC 端新闻 NLP 分析。板子(ESP32-S3)抓新闻存 SD(JSONL)，这一端做分析。
目标部署：Radxa Cubie A7A 6GB(aarch64 Linux，跑完整系统，部署=拷代码+pip install，非烧录)。
开发环境：Windows + WSL2 Ubuntu(任意发行版)。项目根目录可放任意位置,详见根目录 README.md。

## 目录结构（当前）

```
newsbox-nlp\
├── start.bat            ← 一键启动panel
├── 路线图.md            ← 战略路线 + 当前决策
├── device\              ← 上板子的核心
│   ├── main.py           # 拉取/分析入口
│   ├── analyze.py        # NLP 核心(词典+NER+受控+过滤)
│   ├── radar.py          # 加速榜算法
│   ├── 数据\             # companies.csv / stopwords / sectors / events
│   ├── requirements.txt
│   └── README.md
├── lab\              ← 改进 NLP 的工具(不上板)
│   ├── build_dict.py     # 拉 A股+美股 → companies.csv
│   ├── eval.py           # 评估
│   └── notes.md          # 本文件
└── panel\                ← Web 前端 + 后端
    ├── server.py         # FastAPI
    ├── dashboard.html
    └── README.md

纪律：device代码极简(主代码 ≤ 4 文件)；lab干活产出数据 → device只加载消费。
```

## NLP 质量方案：分层混合（核心）

要解决两个病：
- 病A 抽不出主体(公司名)：raw 关键词抽出"融资/获得"，抽不出"宁德时代"。
- 病B 抽出过宽大类("半导体/股票/市场/公司")当主体。

认知：病B 的"半导体"不是垃圾，是错位 → 不删，归到板块栏。
正确输出不是关键词串，而是结构化四栏：实体(谁) / 板块 / 事件 / 残余关键词。

四层处理：
1. 词典 gazetteer：股票名单灌进 jieba(load_userdict) + 直接匹配 → 高精度命中已知公司 + 带出代码/行业。
2. NER 模型：补抓词典外主体(华为/字节/OpenAI/人名/机构 — 这些未上市，股票名单抓不到)。
   NER 抽出 ORG 后反查词典：命中=已上市(升级带代码/行业)，未命中=未上市机构。
3. 受控分类：板块用固定词表(申万行业/GICS)，事件用固定表(融资/IPO/财报/并购/监管/发布/人事/诉讼)。
4. 停用词 + 词性过滤：通用大词进 stopwords；jieba 词性只留 nr/ns/nt/nz 专名，通用名词天然滤掉。

歧义压制(苹果=公司/水果，Apple/Meta/Block 等常用词)：
- 来源加权(财经源放宽)、上下文门控(周围有"股价/财报/CEO"才判公司)、置信度而非硬判。

落地顺序：先做 第1层+第4层(词典+停用/词性)，跑通看效果，再加 第2层 NER 与 第3层受控分类。

## companies.csv 列（已定，先这样）

| 列 | 说明 |
|---|---|
| code | 股票代码(A股6位 / 美股ticker) |
| name | 公司名称 |
| alias | 别名/简称(多个用;分隔，如 宁德;CATL) |
| industry | 行业 |
| exchange | 交易所(SH/SZ/NASDAQ/NYSE) |

数据源(免费)：A股 akshare ak.stock_info_a_code_name()；美股 SEC company_tickers.json；行业 akshare 申万。
lab需额外依赖：akshare（不进device requirements）。

## 待办（按顺序）
- [x] device外围搭好：main.py(拉取→存档→分析→落盘) + analyze.py(基线NLP,可替换)。
      已用 --from-file 样例跑通；输出 仓库/news_raw.jsonl + analyzed.jsonl(四栏结构,UTF-8中文OK)。
      接缝：改进NLP只重写 analyze.py 的 analyze()，main.py 不动。
      待板子 P2 上线后用 --board host:port 真连。
- [x] build_dict.py：A股(akshare stock_info_a_code_name 5529)+美股(SEC company_tickers 10433)→ companies.csv 共15962家(列code/name/alias/industry/exchange)。akshare A股接口偶发ConnectionReset, 重试即可。
- [x] device/数据：stopwords.txt(过宽停用词) / sectors.txt(板块) / events.txt(事件) 初版词表。
- [x] analyze.py：第1层词典(中文jieba.add_word公司名+切词命中→带股票代码; 英文ticker须大写≥3字+核心名首字母大写≥5字+缩写/歧义黑名单)+第3层板块/事件substring+第4层停用词&jieba词性(allowPOS n/nz/nt/nr/ns/vn)过滤关键词。输出四栏entities/sectors/events/keywords。
- [x] eval.py：内置A股例句验证+读analyzed.jsonl统计覆盖。
      实测235条真实数据: 中文极佳(宁德时代300750/贵州茅台600519/比亚迪002594/中芯国际688981全带代码, 板块事件分得清); 英文从150垃圾降到6(Microsoft/Nvidia/Broadcom对, 残留GEO/Glimpse等扁平词典固有噪声)。
- [x] **第2层 NER(混合)**: spacy zh/en_core_web_sm。中文小模型ORG召回弱→混合:NER抓ORG(英文公司+未上市腾讯/三星/OpenAI+多词名)+中文仍靠词典(A股召回主力)。_NER_STOP过滤EU/API/LLM缩写, _CN_AMBIG排除机器人/新产业。覆盖率 8%→公司机构数226→1821。
- [x] **Webpanel(panel/)**: server.py(SQLite + 通用下钻/api/tag无上限 + 关键词入库) + dashboard.html(任意标签点开看全部来源新闻, 标题链原文, 图表onClick下钻) + start.bat。
- [x] **加速榜(device/radar.py)**：上游 3× 加权 + Poisson surprise + 上游徽章。
- [x] **中文 substring 词典匹配**：A股公司名(≥3字)长名优先 substring 命中 text，绕过 jieba 切词漏。中文上游带代码实体 0 → 194+。
- [x] **6 个上游源**: SEC EDGAR / GlobeNewswire / PRNewswire / wallstreetcn(global) / wscn-astock / dongcai-kx。
- [ ] **P-C 加速榜重构**(已决策，待实施)：
  - 双赛道：上游加速榜 + 新闻加速榜，不再加权混合
  - 基线自适应：EWMA z-score (α≈0.15)，公式见路线图.md
  - 加速榜行内 sparkline + 点开大图
- [ ] **公司榜清理**：删折线图(已挪到加速榜)；只留累计排行榜。
- [ ] **板块/事件 自适应基线**(同 EWMA z-score)，类比加速榜。
- [ ] NER 残留噪声(短缩写/泛机构) → 大NER模型 / 上下文消歧 / 黑名单迭代。
- [ ] 别名/行业补充(companies.csv 的 alias/industry 列现为空)。
- [ ] 自动定时拉取入库 + 接行情数据回测领先性 + 可选 LLM 摘要。

## device ↔ 板子 接口契约（P2 已实现）
GET http://<板子>/news?since=<unix_ts> → 返回 JSONL，仅 time>since 的新闻。
USB 串口: SINCE <ts> 命令；返回 <<<NEWS BEGIN>>>..<<<NEWS END>>> 帧。
板子分 /news 和 /upstream 两个目录, P2 同时返回二者。
