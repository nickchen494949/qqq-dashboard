# PROJECT_CONTEXT

> 每次新对话先读这个文件。它告诉你项目现在走到哪里。

---

## 目标

做一套 TQQQ 三层防守系统 + 自动化 Dashboard。
Dashboard 地址：https://nickchen494949.github.io/qqq-dashboard/

---

## 主策略（已封版）

```
正常环境：100% TQQQ
波动危险：66% TQQQ
信用危险：33% TQQQ
Fed 变鹰：0% TQQQ

优先级：Fed > Credit > Vol > Normal
```

### 第一层：Fed SEP
- 同一 target year 里 Core PCE 上修 AND Fed Funds Rate 上修 AND Core PCE > 2% → 0%
- 不受 NSL 约束，强制清仓

### 第二层：Credit Z = -ZScore(HYG/IEF)
- Trigger > 1.2 → 33%，Recover < 0.2 → 恢复
- 受 NSL 约束

### 第三层：Vol Z = 20D realized vol Z-score
- Trigger > 1.0 → 66%，Recover < -0.5 → 恢复
- 受 NSL 约束

### NSL（Never Sell in Loss）
- 赚钱时允许降仓
- 亏损时 Credit/Vol 不强制降仓
- Fed SEP 例外，可强制 0%

### 执行
- 收盘产生信号 → 次日开盘执行（T+1）
- 换仓当天：gap 用旧仓位，intraday 用新仓位

---

## 封版参数（不可修改，除非通过完整测试协议）

```
Credit:  Trigger = 1.2,  Recover = 0.2
Vol:     Trigger = 1.0,  Recover = -0.5,  Lev = 66%
TC:      25 bps per switch
NSL:     on
```

---

## 封版性能（29/29 生产级检查全过）

```
CAGR:      +54.5%
MDD:       -38.7%
Sharpe:    1.36
Trades:    40（年均 2.8 次）
回测期:    2012-01 → 2026-05（14.3 年）
```

---

## 三条铁律

1. **Always build on NSL** — 所有策略修改必须保留 NSL
2. **Always push to Git** — 每次修改必须 commit + push
3. **Always run full testing protocol** — 新策略必须通过：
   - T+1 执行（不接受 T+0）
   - IS 2012-2018 → Holdout 2019-2022 → Forward 2023-2026，所有期 Sharpe > 0.5
   - 参数高原 ≥ 5 个组合
   - TC stress test（200 bps 仍 Sharpe > 1.0）
   - 5 项封版硬检查（MDD ≤ -40%, Sharpe ≥ Credit-only+0.05, CAGR loss ≤ 2pp, TC200 Sharpe > 1.0, trades ≤ 4/yr）

---

## 不要重复的失败方向

| # | 信号 | 结果 | 失败原因 |
|:---|:---|:---|:---|
| 1 | EPS 加速度 | CAGR -5% | 45 天数据延迟 |
| 2 | EPS 绝对增速 | r = -0.09 | 无预测力 |
| 3 | EPS 均值回归 | CAGR -1.5% | 顶部停留太久 |
| 4 | VIX Backwardation | CAGR -0.7% | 是抄底信号不是逃跑信号 |
| 5 | HY OAS 信用利差 | 数据太短 | 同步/抄底指标 |
| 6 | VIX+Momentum Warning | T+0: +7.2%, **T+1: -1.5%** | look-ahead bias，最危险的假信号 |

### 已验证的研究（2024-05-31）

**2D Joint Grid Search (Credit Lev × Vol Lev)**
- 用完整审计引擎（SEP+NSL+Next-Open+Costs）跑 7×7 = 49 种组合
- SEP out = 629 days，与审计完全匹配
- **发现：当前参数 (Credit=1.0x, Vol=2.0x) ✅ 在高原上**
- Best Sharpe = 1.28 (Credit=1.0x, Vol=0.0x)，当前 = 1.26，差 0.02
- **高原范围：Credit 0.5x–1.5x，Vol 0.0x–3.0x（15/49 = 31%）**
- **关键发现：Vol 维度几乎是平的（Sharpe 1.23–1.28），SEP 是主力风控**
- 之前简化引擎（SEP out=0/40）给出错误结论（Vol=2.0x 不在高原），原因是 SEP 缺失导致 Vol 被迫承担全部风控

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
│   ├── build_dashboard.py           # 主程序（数据+回测+HTML）
│   ├── audit_backtest.py            # 29 项生产审计
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
- Credit Z: -2.25（安全）
- Vol Z: 0.12（安全）
- Leverage: 3x（100% TQQQ）
- Dashboard: 在线运行中

---

## 下一步

- 维护 dashboard，确保每日自动更新正常
- 监控 live signal（下一次 FOMC SEP: 2026-06-17）
- 如果有新研究方向，必须先通过完整测试协议
