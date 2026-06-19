# 世界杯预测终端

本项目是本地运行的世界杯多比赛预测与赔率监控面板。第一版不依赖第三方 Python 包，使用 Python 标准库提供本地 Web 服务、SQLite 快照存储和原生 HTML/JS 图表。

## 启动

```powershell
python run_dashboard.py
```

打开：

```text
http://127.0.0.1:8765
```

## 线上部署与自动刷新

Vercel 是 serverless 环境，不能依赖本地后台线程长期运行。线上刷新使用 GitHub Actions：

```text
.github/workflows/refresh-data.yml
```

规则：

```text
每 4 小时运行一次 scripts/refresh_for_deploy.py
刷新赛程、赔率、当前四场预测和预测快照
写入 data/matches.json、data/refresh_status.json、data/latest_predictions.json、data/serverless_prediction_snapshots.json
如文件有变化则自动 commit + push
Vercel 监听 GitHub 后自动重新部署并读取最新 JSON
```

线上状态接口：

```text
/api/refresh/status
```

本地运行 `python run_dashboard.py` 时，仍会启动本地后台刷新线程；线上以 GitHub Actions 为准。

## 当前能力

- 多比赛总览和独立比赛 Tab
- 每场比赛独立 `match_id`，避免数据错乱
- 手动刷新当前比赛或全部比赛
- SQLite 保存赔率快照
- 公开数据源配置 `data/sources.json`
- 数据源健康状态 `data/source_health.json`
- 公开 HTML/JSON 通用适配器，失败后自动降级到手动赔率
- 一键查询公开赛程，区分未开赛和已完结
- 预测快照归档，用于赛后回测
- 回测指标：Top1、Top2、比分 Top1、Brier Score、Log Loss
- v4.3 算法优化：
  - 动态市场权重
  - 爆冷触发器强度评分
  - 保守/开放/爆冷情景比分修正
  - 校准分桶
  - 自动调参建议
- v4.4 总进球/大小球：
  - 总进球 0/1/2/3/4/5/6/7+ 分布
  - 0-1、2-3、4+ 区间
  - 大/小1.5、2.5、3.5 概率和倾向
- v5.0 盘口价值与体彩执行层：
  - 市场赔率去水作为底盘
  - 基本面和临场变量只做小幅 log 修正
  - softmax 输出模型胜平负概率
  - 体彩胜平负、让球胜平负、比分、总进球、半全场映射
  - 公允SP、EV、Kelly、风险分、建议动作、放弃原因
  - 复选包按注数重算 EV，避免只看命中率
- v5.9 行动分与首页决策闭环：
  - 在模型概率、EV、风险分、玩法稳定性、官方SP可买性之上生成行动分
  - 候选项分为主推、可搭配、防冷小注、观察、放弃、不可下单
  - 首页展示最新完赛复盘、最近待开比赛、今日下单清单和金额拆分
  - 缺少体彩SP、EV≤0或风险收益不匹配的选项不会进入首页下单清单
- 胜平负概率、比分分布、大小球、双方进球
- 六情景预测：
  - 基准模型
  - 市场校准模型
  - 临场信息模型
  - 保守节奏模型
  - 开放节奏模型
  - 爆冷情景模型
- 赔率隐含概率曲线
- 比分热力图
- 进球数分布
- 9 维评分雷达
- 爆冷雷达
- 数据完整度评分
- 模型/市场分歧等级

## 比赛配置

比赛清单在：

```text
data/matches.json
```

第一次启动会自动生成示例比赛。每场比赛可以配置：

```json
{
  "match_id": "BRA_MAR_SAMPLE",
  "home_team": "巴西",
  "away_team": "摩洛哥",
  "kickoff": "2026-06-13T06:00:00+08:00",
  "home_elo": 2140,
  "away_elo": 1960,
  "manual_odds": {"home": 1.72, "draw": 3.85, "away": 5.2},
  "expected_goals": {"home": 1.75, "away": 0.95},
  "upset_triggers": {
    "underdog_low_block": true,
    "underdog_counter_speed": true
  }
}
```

可选体彩执行字段：

```json
{
  "sporttery_handicap": -1,
  "sporttery_sp": {
    "胜平负": {"胜": 1.72, "平": 3.85, "负": 5.20},
    "让球胜平负": {"让胜": 3.10, "让平": 3.45, "让负": 1.88},
    "总进球": {"0": 10.0, "1": 4.5, "2": 3.4, "3": 3.7, "4": 5.2, "5": 8.5, "6": 16.0, "7+": 25.0}
  }
}
```

没有体彩 SP 时，工具只输出概率和“缺少SP”原因；胜平负可用普通市场赔率代理做价值判断演示，但会标记为 `market_h2h_proxy`。

## 赔率 API

如果设置环境变量 `THE_ODDS_API_KEY` 且比赛配置里有 `odds_event_id`，刷新时会尝试调用 The Odds API。否则使用 `manual_odds` 生成本地快照，保证面板可以先跑通。

```powershell
$env:THE_ODDS_API_KEY="your_key"
python run_dashboard.py
```

## 无 Key 公开源

如果不想接需要 key 的 API，可以把公开页面或公开 JSON 固化到：

```text
data/sources.json
```

支持两种通用源：

```text
public_html_regex   # 用正则从公开 HTML 页面提取主胜/平/客胜
public_json_path    # 用点路径从公开 JSON 提取主胜/平/客胜
```

工作原则：

```text
AI 负责发现和判断候选源
脚本只抓已经写入 sources.json 且 enabled=true 的公开源
不做登录、验证码、加密签名或反爬绕过
抓取失败写入 source_health.json，并自动降级到 manual_odds
```

已内置的官方体彩公开源：

```text
source_id: sporttery_mobile_calculator
入口页: https://m.sporttery.cn/mjc/jsq/zqbf/
接口: https://webapi.sporttery.cn/gateway/uniform/football/getMatchCalculatorV1.qry
玩法: 胜平负、让球胜平负、比分、总进球、半全场
```

该源用于抓取中国体彩 SP。若官方 WAF 或访问策略临时拦截服务器端请求，系统会记录到 `data/source_health.json` 并继续使用最近成功快照或手动赔率兜底；不会绕过登录、验证码或安全防护。

## 体彩计算器对齐报告

当输出下注参考 Excel 时，使用：

```powershell
node work\build_sporttery_aligned_report.mjs
```

该报告按体彩计算器真实玩法分 sheet：

```text
体彩-胜平负
体彩-让球胜平负
体彩-总进球
体彩-比分
体彩-半全场
候选池
串关池
放弃清单
体彩SP快照
```

规则：

```text
只对已抓到 SP 的选项计算 EV。
胜平负如果体彩未开售，不生成下注推荐。
让球胜平负必须有官方让球数 H；缺少 H 时只显示“不可用”，不计算 EV。
比分和半全场即使 EV 高，也默认作为高风险玩法处理。
```

## 数据文件

```text
data/odds_snapshots.sqlite
```

保存每次刷新产生的赔率快照。

同时保存：

```text
fixtures              # 公开赛程和赛果
prediction_snapshots  # 每次归档的预测概率
backtest_results      # 赛后回测结果
```

## 赛程和回测

面板里的“赛程/回测”页提供三个动作：

```text
一键查询赛程      # 拉取公开赛程源，写入 fixtures
归档当前预测      # 将当前所有比赛的六情景预测写入 prediction_snapshots
运行赛后回测      # 对已完结且有预测归档的比赛计算准确率
```

回测用途：

```text
Top1 命中率      # 概率最高结果是否命中
Top2 命中率      # 实际赛果是否在概率前二
Brier Score      # 概率校准质量，越低越好
Log Loss         # 对错误高置信预测惩罚更重，越低越好
比分 Top1 命中率 # 最高概率比分是否命中
校准分桶          # 检查不同置信区间是否校准
自动调参建议      # 根据分情景回测表现给出规则调整方向
```

## 设计原则

模型不是给唯一答案，而是给多组参考：

- 模型怎么看
- 市场怎么看
- 临场信息是否改变判断
- 爆冷路径是否成立
- 数据完整度是否足够支撑结论
- 看好不等于值得下注；只有模型概率高于价格隐含概率，且 EV 为正，才进入候选池
- 串关只从正 EV 候选生成，不能把负 EV 低赔热门硬串
