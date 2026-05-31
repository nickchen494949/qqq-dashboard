# 研究规则（Research Protocol）

> 所有未来的策略研究、参数调整、新信号测试，都必须遵守以下规则。

---

## 三条铁律

### 1. Never Sell in Loss（NSL）是绝对前提

所有新策略、新信号、新参数组合都必须建立在 NSL 之上。

```
如果 trade 盈利 → 允许降仓
如果 trade 亏损 → Credit/Vol 不强制降仓
Fed SEP 变鹰    → 唯一例外，强制 0%
```

**任何违反 NSL 的策略变体都不被接受，即使它能提高 Sharpe。**

---

### 2. 每次修改必须同步 Git

```bash
# 修改代码后
git add -A
git commit -m "描述你改了什么"
git push origin main
```

**不允许本地有未提交的策略代码。所有研究过程必须有版本记录。**

---

### 3. 所有新策略必须通过完整测试协议

#### 基础测试（必须全过）

| # | 测试 | 方法 | 通过标准 |
|:---|:---|:---|:---|
| 1 | T+1 执行 | 收盘信号 → 次日开盘执行 | CAGR > 0（不接受 T+0） |
| 2 | 信号延迟验证 | 逐笔检查 exec_date > signal_date | 100% 通过 |
| 3 | In-Sample / Out-of-Sample | IS 2012-2018 → Holdout 2019-2022 → Forward 2023-2026 | 所有期 Sharpe > 0.5 |
| 4 | 参数高原 | Grid search, plateau ≥ 5 个组合在最优 Sharpe ± 0.05 | 不是孤立尖峰 |
| 5 | TC Stress Test | 0 / 25 / 50 / 100 / 200 bps | TC=200 仍有正 Sharpe |

#### 5 项封版硬检查（从 candidate 升级到 production）

| # | 检查项 | 通过标准 |
|:---|:---|:---|
| 1 | Max Drawdown | ≤ -40% |
| 2 | Sharpe vs Credit-only | ≥ Credit-only Sharpe + 0.05 |
| 3 | CAGR loss vs Credit-only | ≤ 2pp |
| 4 | TC 200bps Sharpe | > 1.0 |
| 5 | 年均交易次数 | ≤ 4 次 |

#### 防过拟合额外检查

| # | 测试 | 方法 |
|:---|:---|:---|
| 6 | 合成 vs 真实 ETF | TQQQ/QLD/QQQ 真实收益对比合成杠杆，差异 < 15pp |
| 7 | C2C vs Next-Open gap | Close-to-close vs Next-open 差异 < 5pp |
| 8 | 跨资产验证 | 同策略套用 SPY/UPRO，仍 beat B&H |
| 9 | 消融实验 | 新增信号必须独立验证有效（拆开 vs 叠加对比） |

---

## 当前封版参数（不可修改，除非通过完整测试协议）

```
Credit:  Trigger = 1.2,  Recover = 0.2
Vol:     Trigger = 1.0,  Recover = -0.5,  Lev = 66%
TC:      25 bps per switch
NSL:     Credit/Vol 盈利时降仓；Fed 不受约束
```

## 当前封版性能（2012–2026, 29/29 PASS）

```
CAGR:      +54.5%
MDD:       -38.7%
Sharpe:    1.36
Trades:    40（年均 2.8 次）
```

---

## 失败教训（必须牢记）

1. **T+0 是骗人的。** VIX+Mom Warning 在 T+0 显示 Sharpe 1.95，但 T+1 完全归零。
2. **EPS 永远滞后 45 天。** 不管统计多显著，交易上都亏钱。
3. **统计显著 ≠ 可交易。** 均值回归 p=0.0002 但 CAGR 为负。
4. **VIX 是抄底信号，不是逃跑信号。** Backwardation 做反方向会亏。
5. **6 个 secondary signal 全部失败。** 除非通过完整测试协议，否则不要浪费时间。
