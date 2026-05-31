# TQQQ 三层防守系统

这套系统不是预测每天涨跌。它只判断一件事：

> **现在应该拿多少 TQQQ？**

## 仓位

```text
正常环境：100% TQQQ
波动危险：66% TQQQ
信用危险：33% TQQQ
Fed 变鹰：0% TQQQ
```

优先级：

```text
Fed > Credit > Vol > Normal
```

---

## 1. Fed / SEP：最大开关

看 Fed SEP 是否变鹰。

规则：

```text
同一个 target year 里：
Core PCE 上修
AND Fed Funds Rate 上修
AND Core PCE > 2%
→ 0% TQQQ
```

人话：

> Fed 觉得未来通胀更高、利率也更高，就不要拿 TQQQ。

---

## 2. Credit：信用风险开关

指标：

```text
Credit Z = -ZScore(HYG / IEF)
```

规则：

```text
Credit Z > 1.2 → 进入信用危险
Credit Z < 0.2 → 解除信用危险
```

仓位：

```text
信用危险 + 赚钱 → 33% TQQQ
信用危险 + 亏损 → 保持 100% TQQQ（NSL）
```

人话：

> 垃圾债相对国债变弱，市场风险偏好变差，就大幅降仓。

---

## 3. Vol：波动风险开关

指标：

```text
Vol Z = 20D realized volatility 的 Z-score（相对 252 日历史）
```

规则：

```text
Vol Z > 1.0  → 进入波动危险
Vol Z < -0.5 → 解除波动危险（宽迟滞防 whipsaw）
```

仓位：

```text
波动危险 + 赚钱 → 66% TQQQ
波动危险 + 亏损 → 冻结当前仓位
```

人话：

> 市场波动明显升高，但还不是信用危机，就先轻度降仓。

---

## 4. NSL：不亏钱砍仓

```text
如果当前 trade 有利润 → 允许降仓
如果当前 trade 亏损   → Credit/Vol 不强行降仓
```

Fed/SEP 是最高级别风险，独立强制 0%，不受 NSL 约束。

人话：

> 赚钱时收风险，亏损时不被噪音震出去。

---

## 5. 执行

```text
今天收盘产生信号
下一交易日开盘执行
```

换仓当天：

```text
隔夜 gap → 用旧仓位
开盘后 intraday → 用新仓位
```

---

## 6. 实操（只用 TQQQ 一只股票）

| 策略仓位 | 实操 |
|:---|:---|
| 100% TQQQ | 全仓 TQQQ |
| 66% TQQQ | 66% TQQQ + 34% 现金 |
| 33% TQQQ | 33% TQQQ + 67% 现金 |
| 0% TQQQ | 全部现金 |

不需要买 QLD 或 QQQ，只调 TQQQ 仓位比例即可。

---

## 7. 封版参数

```text
Credit:  Trigger = 1.2,  Recover = 0.2
Vol:     Trigger = 1.0,  Recover = -0.5,  Lev = 66%
TC:      25 bps per leverage switch
```

## 8. 验证结果（2012–2026）

```text
CAGR:     54.2%
MDD:      -38.3%
Sharpe:   1.33
Trades:   39（年均 2.8 次）
TC 200bps Sharpe: 1.15
```

---

## 一句话总规则

> **平时 100% TQQQ；波动升高降到 66%；信用变差降到 33%；Fed 变鹰降到 0%。Credit/Vol 降仓受 NSL 约束，不在亏损时乱砍。**
