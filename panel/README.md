# panel（newsbox 情报台前端）

独立的 Web 前端 + 后端，**暂不并入device**，后期移植到 Cubie。

- `server.py` —— FastAPI：读 `../device/store/analyzed.jsonl` → SQLite(`newsbox.db`) → REST API + 提供页面
- `dashboard.html` —— 单文件前端（纯文字导航 + Chart.js 图表 + 公司下钻），自带暗色适配

## 跑
```bash
# 先确保有分析结果: cd ../device && python main.py --usb /dev/ttyACM0 (或 --from-file 样例)
pip install fastapi uvicorn        # device requirements 已含
python server.py                   # 0.0.0.0:8000
# 浏览器开 http://localhost:8000  (局域网用 http://<本机IP>:8000)
```
数据更新后点页面右上角「重新载入」重建 SQLite。

## 页面
概览(KPI+新闻量) / 新闻流(带标签卡片) / 公司(趋势对比+排行→点进看单公司趋势与相关新闻) / 板块(热度条) / 事件(分布环)

## API
`/api/overview` `/api/companies` `/api/company/{名}` `/api/sectors` `/api/events` `/api/feed?lang=cn&limit=30` `POST /api/rebuild`

## 移植到板子
后期把本目录并入 device，或让device main.py 落盘后由本 server 提供。前端纯静态、后端纯 SQLite，aarch64 直接跑。
