# PROJECT_CONTEXT

> 每次新对话先读 `AI_READ_FIRST.md`，然后读这个文件。它告诉你项目现在的详细技术细节与架构原则。

---

## 目标与系统真相
维持并运行 TQQQ 四层防守系统 (v2-sealed) 及其自动化 Dashboard。
该仓库是生产策略与研究历史的绝对唯一真相源 (Absolute Source of Truth)。

---

## 状态：CLOSED (v2-sealed, 2026-08-13 snapshot)
**v2-sealed 生产架构的选择和参数调优已于 2026-08-13 冻结快照时正式关闭。**

- **严禁再修改参数**：不允许使用 2026-08-13 之后的新 OOS 数据去反向拟合 (refit) v2-sealed。
- **允许的未来研究**：仅允许作为独立的 challenger 研究，以及真正的 OOS (Out-of-Sample) 跟踪验证。
- **Vol 层状态**：由于历史 bootstrap 信心相对较弱，保留为 tactical airbag，但仍在进行 OOS validation 观察。

---

## 主策略架构 (4 Layers)
```
正常环境：100% TQQQ (3x)
Vol 危险：  66% TQQQ (2x)
通胀危险：  33% TQQQ (1x)
信用危险：  33% TQQQ (1x)
Fed 变鹰：   0% TQQQ (0x)

优先级：SEP > Credit > TIP/TLT > Vol > Normal
```

### 第一层：Fed SEP (Macro Environment)
- 同一 target year 里 Core PCE 上修 AND Fed Funds Rate 上修 AND Core PCE > 2% → 0%
- 不受 NSL 约束，可强制清仓 (0x)
- Re-entry：仅当上述三个条件不再同时满足时，允许恢复。

### 第二层：Credit Z = -ZScore(HYG/IEF, 252d)
- 衡量高收益公司债与国债避险资产的信用利差压力。
- 受 NSL 约束。

### 第三层：TIP/TLT Z = ZScore(TIP/TLT ratio, 63d)
- 衡量债券市场的通胀重新定价压力 (bond-market / duration / inflation repricing stress)。
- 受 NSL 约束。
- 经常先于 Credit/Vol 触发，提供早期 leverage divergence。

### 第四层：Vol Z = 20D realized vol Z-score (252d)
- 基于 QQQ 每日收益的已实现波动率 Z-score (20D realized volatility Z-score based on QQQ daily returns)。
- 战术级安全气囊，受 NSL 约束。

---

## 封版参数 (v2, 严禁未经授权修改)
```
Credit:  Trigger = 1.2,  Recover = 0.5 → 1x
TIP/TLT: Trigger = 2.5,  Recover = 0.3,  Lev = 1x,  Window = 63d
Vol:     Trigger = 1.5,  Recover = 0.5,  Lev = 2x
TC:      25 bps per switch
NSL:     ON
```

---

## 核心执行原则

### 1. NSL (Anti-whipsaw Re-entry Gate)
- 原名 Never Sell in Loss。
- **机制**：盈利时，系统允许随着 danger 信号的解除战术性加仓（恢复杠杆）。**亏损时，系统限制加仓恢复（阻止重新进场）。**
- 主要价值来自在 SEP 导致 0x 清仓后，防止系统在 danger 状态尚未完全解除时过早因为一次小反弹就被骗回场内 (whipsawing)。
- 它是 v2-sealed 的核心 behavior，绝对禁止为了局部回测而“修复”它，除非对整个系统重新审计和封版。

### 2. T+1 执行 (T+1 Execution)
- 收盘产生信号 → 次日开盘执行（必须是 T+1，禁止 T+0）。
- 换仓当天：gap (C2C) 使用旧仓位，intraday 使用新仓位。

### 3. 数据完整性防御
- Dashboard 的 QQQ/TQQQ 价格获取绝不允许静默 fallback 给过期的静态数据。
- 如果数据超出合理的新鲜度窗口，构建应当 Loud Failure，绝不能部署 stale market data。

---

## 审计标准 (v2 Standard)
任何涉及底层架构变更的 Challenger 模型必须通过以下完整审计才能被考虑：
1. Sharpe > 1.33, MDD > -45%
2. TC 200bps Sharpe > 1.0
3. 交易次数/年 ≤ 5
4. IS (2012-18), Holdout (2019-22), FWD (2023-26) 三个时期 Sharpe 必须全部 > 0.5
5. 参数存在高原 (Plateau ≥ 5 个组合)
6. T+1 必须独立复现，Match rate ≥ 90%
7. 必须通过完整的 block-bootstrap ablation 测试，证明模块级 synergy。
