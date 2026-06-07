# PROJECT_CONTEXT

> 每次新对话先读这个文件。它告诉你项目现在走到哪里。

---

## 目标

做一套 TQQQ 四层防守系统 + 自动化 Dashboard。
Dashboard 地址：https://nickchen494949.github.io/qqq-dashboard/

---

## 主策略（v2 封版，git tag: v2.0-sealed）

```
正常环境：100% TQQQ (3x)
Vol 危险：  66% TQQQ (2x)
通胀危险：  33% TQQQ (1x)
信用危险：  33% TQQQ (1x)
Fed 变鹰：   0% TQQQ (0x)

优先级：Fed > Credit > TIP/TLT > Vol > Normal
```

### 第一层：Fed SEP
- 同一 target year 里 Core PCE 上修 AND Fed Funds Rate 上修 AND Core PCE > 2% → 0%
- 不受 NSL 约束，强制清仓

### 第二层：Credit Z = -ZScore(HYG/IEF, 252d)
- Trigger > 1.2 → 1x，Recover < 0.5 → 恢复
- 受 NSL 约束

### 第三层：TIP/TLT Z = ZScore(TIP/TLT ratio, 63d)
- Trigger > 2.5 → 1x，Recover < 0.3 → 恢复
- 受 NSL 约束
- 抓住"利率/通胀压力还没变成信用崩盘前"的阶段

### 第四层：Vol Z = 20D realized vol Z-score (252d)
- Trigger > 1.5 → 2x，Recover < 0.5 → 恢复
- 受 NSL 约束

### NSL（Never Sell in Loss）
- 赚钱时允许降仓
- 亏损时 Credit/TIP/Vol 不强制降仓
- Fed SEP 例外，可强制 0%

### 执行
- 收盘产生信号 → 次日开盘执行（T+1）
- 换仓当天：gap 用旧仓位，intraday 用新仓位

---

## 封版参数（v2，不可修改，除非通过完整测试协议）

```
Credit:  Trigger = 1.2,  Recover = 0.5
TIP/TLT: Trigger = 2.5,  Recover = 0.3,  Lev = 1x,  Window = 63d
Vol:     Trigger = 1.5,  Recover = 0.5,  Lev = 2x
TC:      25 bps per switch
NSL:     on
```

### v1 → v2 参数变更

| Param | v1 | v2 | Reason |
|:---|:---|:---|:---|
| Credit Recover | 0.2 | **0.5** | CAGR 优化，在高原上 |
| Vol Trigger | 1.0 | **1.5** | 减少 whipsaw |
| Vol Recover | -0.5 | **0.5** | 更快恢复 |
| TIP/TLT | 不存在 | **T=2.5 R=0.3 L=1x** | 新增第三层 |

---

## 封版性能（v2，26/26 生产级检查全过）

```
CAGR:      +58.6%
MDD:       -37.4%
Sharpe:    1.53
Trades:    62（年均 4.3 次）
回测期:    2012-01 → 2026-06（14.3 年）

IS (2012-2018):      Sharpe 1.36
Holdout (2019-2022): Sharpe 1.58
Forward (2023-2026): Sharpe 1.81
TC200 Sharpe:        1.14
```

### v1 baseline（已降级）

```
CAGR:      +54.5%
MDD:       -38.7%
Sharpe:    1.36
Trades:    40（年均 2.8 次）
```

---

## 审计标准

### v2 standard（当前）

| Check | Required |
|:---|:---|
| Sharpe | > 1.33 |
| MDD | > -45% |
| TC200 Sharpe | > 1.0 |
| trades/yr | ≤ 5 |
| IS/Holdout/FWD Sharpe | > 0.5 each |
| Parameter plateau | ≥ 5 points |
| T+1 independent | ≥ 90% match |

### v1 standard（旧，仅供参考）

```
Sharpe > 1.0, MDD > -40%, trades/yr ≤ 4, TC200 > 1.0
```

v2 trades/yr 从 4 放宽到 5，因为 TIP/TLT 层增加了 signal coverage 和交易次数。

---

## 三条铁律

1. **Always build on NSL** — 所有策略修改必须保留 NSL
2. **Always push to Git** — 每次修改必须 commit + push
3. **Always run full testing protocol** — 新策略必须通过：
   - T+1 执行（不接受 T+0）
   - IS 2012-2018 → Holdout 2019-2022 → Forward 2023-2026，所有期 Sharpe > 0.5
   - 参数高原 ≥ 5 个组合
   - TC stress test（200 bps 仍 Sharpe > 1.0）
   - 26 项 v2 封版硬检查

---

## 不要重复的失败方向

| # | 信号 | 结果 | 失败原因 |
|:---|:---|:---|:---|
| 1 | EPS 加速度 | CAGR -5% | 45 天数据延迟 |
| 2 | EPS 绝对增速 | r = -0.09 | 无预测力 |
| 3 | EPS 均值回归 | CAGR -1.5% | 顶部停留太久 |
| 4 | VIX Backwardation | CAGR -0.7% | 是抄底信号不是逃跑信号 |
| 5 | HY OAS 信用利差 | 数据太短 | 同步/抄底指标 |
| 6 | VIX+Momentum Warning | T+0: +7.2%, **T+1: -1.5%** | look-ahead bias |

---

## 项目结构

```
QQQ_Risk_Strategy/
├── README.md                        # 入口
├── PROJECT_CONTEXT.md               # ← 你正在读的文件
├── docs/
│   ├── STRATEGY.md                  # 策略规则详解
│   ├── RESEARCH_PAPER.md            # 完整研究论文（504 行）
│   └── RESEARCH_RULES.md            # 测试协议详解
├── fomc_sep/                        # 74 份 Fed SEP PDF
├── market_data/                     # Yahoo/FRED 缓存
├── tools/
│   ├── strategy_engine.py           # 核心引擎（单一真相源）
│   ├── build_dashboard.py           # 主程序（数据+回测+HTML）
│   ├── audit_backtest.py            # 26 项 v2 生产审计
│   └── server.py                    # 本地开发服务
└── .github/workflows/
    └── deploy-dashboard.yml         # 每天 08:00 UTC+8 自动部署
```

---

## 持仓追踪

- Nick: 6,326 units TQQQ
- SY: 395 units TQQQ
- 显示 MYR 和 USD，每 30 分钟自动刷新
- 显示当天 % 变化（TQQQ、USD/MYR、Portfolio）

---

## 当前状态

- SEP: IN（满仓）
- Credit Z: -2.26（安全）
- TIP/TLT Z: 0.33（安全）
- Vol Z: 1.96（🔴 DANGER）
- Leverage: 3x → Pending 2x（Vol triggered, waiting NSL）
- Dashboard: 在线运行中

---

## 下一步

- 维护 dashboard，确保每日自动更新正常
- 监控 live signal（下一次 FOMC SEP: 2026-06-17）
- Joint robustness validation: 3,000 random combos + full 6D grid
- 如果有新研究方向，必须先通过完整测试协议
