"""
SOXL vs TQQQ 关系分析
=====================
SOXL = 3x SOXX (半导体指数)
TQQQ = 3x QQQ (纳斯达克100)

核心问题：半导体是纳斯达克的子集吗？它们的关系有多紧？
"""
import os
import numpy as np
import pandas as pd

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'market_data')

def load_csv(name):
    path = os.path.join(DATA_DIR, f'yahoo_{name}.csv')
    s = pd.read_csv(path, index_col=0, parse_dates=True).squeeze()
    return s[~s.index.duplicated(keep='last')]

qqq = load_csv('QQQ')
soxx = load_csv('SOXX')
spy = load_csv('SPY')
iwm = load_csv('IWM')

# Build daily returns
df = pd.DataFrame({
    'QQQ': qqq, 'SOXX': soxx, 'SPY': spy, 'IWM': iwm
}).dropna()
dr = df.pct_change().dropna()

print(f"Data: {dr.index[0].date()} → {dr.index[-1].date()} ({len(dr)} days)")
print()

# ============================================================================
# PART 1: 基本相关性
# ============================================================================
print("=" * 80)
print("PART 1: 日收益率相关矩阵")
print("=" * 80)
print()
corr = dr.corr()
print(corr.round(4).to_string())

# ============================================================================
# PART 2: 波动率对比
# ============================================================================
print("\n")
print("=" * 80)
print("PART 2: 年化波动率 & Beta")
print("=" * 80)

vols = dr.std() * np.sqrt(252)
print(f"\n  年化波动率:")
for col in dr.columns:
    print(f"    {col:>6s}: {vols[col]*100:.1f}%")

print(f"\n  相对 QQQ 的 Beta:")
qqq_var = dr['QQQ'].var()
for col in ['SOXX', 'SPY', 'IWM']:
    beta = dr[col].cov(dr['QQQ']) / qqq_var
    print(f"    {col:>6s}: β = {beta:.3f}")

print(f"\n  相对 SPY 的 Beta:")
spy_var = dr['SPY'].var()
for col in ['QQQ', 'SOXX', 'IWM']:
    beta = dr[col].cov(dr['SPY']) / spy_var
    print(f"    {col:>6s}: β = {beta:.3f}")

# ============================================================================
# PART 3: 滚动相关性
# ============================================================================
print("\n")
print("=" * 80)
print("PART 3: QQQ-SOXX 滚动相关性")
print("=" * 80)

for window in [21, 63, 126, 252]:
    rc = dr['QQQ'].rolling(window).corr(dr['SOXX']).dropna()
    low = (rc < 0.80).mean() * 100
    very_low = (rc < 0.60).mean() * 100
    print(f"\n  {window}d rolling:")
    print(f"    mean={rc.mean():.3f}  min={rc.min():.3f}  max={rc.max():.3f}")
    print(f"    corr < 0.80: {low:.1f}%  |  corr < 0.60: {very_low:.1f}%")

# ============================================================================
# PART 4: 分年度关系
# ============================================================================
print("\n")
print("=" * 80)
print("PART 4: 分年度 — 收益率 & 相关性 & 波动比")
print("=" * 80)

print(f"\n  {'Year':>6s} {'QQQ':>8s} {'SOXX':>8s} {'SOXX/QQQ':>10s} {'Corr':>7s} {'SOXX Vol':>10s} {'VolRatio':>10s}")
print(f"  {'-'*6:>6s} {'-'*8:>8s} {'-'*8:>8s} {'-'*10:>10s} {'-'*7:>7s} {'-'*10:>10s} {'-'*10:>10s}")

for year in range(dr.index[0].year, dr.index[-1].year + 1):
    mask = dr.index.year == year
    if mask.sum() < 20:
        continue
    yr_dr = dr[mask]
    
    qqq_ret = (1 + yr_dr['QQQ']).prod() - 1
    soxx_ret = (1 + yr_dr['SOXX']).prod() - 1
    ratio = soxx_ret / qqq_ret if abs(qqq_ret) > 0.001 else float('nan')
    corr_yr = yr_dr['QQQ'].corr(yr_dr['SOXX'])
    soxx_vol = yr_dr['SOXX'].std() * np.sqrt(252)
    qqq_vol = yr_dr['QQQ'].std() * np.sqrt(252)
    vol_ratio = soxx_vol / qqq_vol
    
    print(f"  {year:>6d} {qqq_ret*100:>+7.1f}% {soxx_ret*100:>+7.1f}% {ratio:>+9.2f}x "
          f"{corr_yr:>6.3f} {soxx_vol*100:>9.1f}% {vol_ratio:>9.2f}x")

# ============================================================================
# PART 5: 尾部行为 — 最大日跌幅
# ============================================================================
print("\n")
print("=" * 80)
print("PART 5: 尾部行为 — 最差的日子")
print("=" * 80)

# Top 20 worst QQQ days
worst_qqq = dr['QQQ'].nsmallest(20)
print(f"\n  QQQ 最差 20 天, SOXX 同日表现:")
print(f"  {'Date':>12s} {'QQQ':>8s} {'SOXX':>8s} {'SOXX/QQQ':>10s}")
for date, val in worst_qqq.items():
    soxx_val = dr.loc[date, 'SOXX']
    ratio = soxx_val / val if abs(val) > 0.001 else 0
    print(f"  {date.date()!s:>12s} {val*100:>+7.2f}% {soxx_val*100:>+7.2f}% {ratio:>9.2f}x")

# Top 20 worst SOXX days
worst_soxx = dr['SOXX'].nsmallest(20)
print(f"\n  SOXX 最差 20 天, QQQ 同日表现:")
print(f"  {'Date':>12s} {'SOXX':>8s} {'QQQ':>8s} {'SOXX/QQQ':>10s}")
for date, val in worst_soxx.items():
    qqq_val = dr.loc[date, 'QQQ']
    ratio = val / qqq_val if abs(qqq_val) > 0.001 else 0
    print(f"  {date.date()!s:>12s} {val*100:>+7.2f}% {qqq_val*100:>+7.2f}% {ratio:>9.2f}x")

# ============================================================================
# PART 6: SOXX 独立崩盘 — SOXX 跌但 QQQ 不跌的日子
# ============================================================================
print("\n")
print("=" * 80)
print("PART 6: SOXX 独立崩盘 — SOXX 跌 >3% 但 QQQ 跌 <1%")
print("=" * 80)

soxx_crash = (dr['SOXX'] < -0.03) & (dr['QQQ'] > -0.01)
soxx_crash_days = dr[soxx_crash].sort_values('SOXX')
print(f"\n  共 {len(soxx_crash_days)} 天")
if len(soxx_crash_days) > 0:
    print(f"\n  {'Date':>12s} {'SOXX':>8s} {'QQQ':>8s} {'SPY':>8s}")
    for date, row in soxx_crash_days.head(20).iterrows():
        print(f"  {date.date()!s:>12s} {row['SOXX']*100:>+7.2f}% {row['QQQ']*100:>+7.2f}% {row['SPY']*100:>+7.2f}%")

# ============================================================================
# PART 7: 3x 模拟 — 回撤对比
# ============================================================================
print("\n")
print("=" * 80)
print("PART 7: 3x 杠杆模拟 — 最大回撤对比")
print("=" * 80)

for name, returns in [('QQQ (→TQQQ)', dr['QQQ']), ('SOXX (→SOXL)', dr['SOXX'])]:
    eq_3x = (1 + 3 * returns).cumprod()
    eq_1x = (1 + returns).cumprod()
    mdd_3x = (eq_3x / eq_3x.expanding().max() - 1).min()
    mdd_1x = (eq_1x / eq_1x.expanding().max() - 1).min()
    cagr_3x = eq_3x.iloc[-1] ** (252/len(eq_3x)) - 1
    cagr_1x = eq_1x.iloc[-1] ** (252/len(eq_1x)) - 1
    
    print(f"\n  {name}:")
    print(f"    1x: CAGR={cagr_1x*100:+.1f}%, MDD={mdd_1x*100:.1f}%")
    print(f"    3x: CAGR={cagr_3x*100:+.1f}%, MDD={mdd_3x*100:.1f}%")

# ============================================================================
# PART 8: 持仓重叠
# ============================================================================
print("\n")
print("=" * 80)
print("PART 8: QQQ vs SOXX — 持仓关系")
print("=" * 80)

print("""
  QQQ (Nasdaq 100) 前十大持仓 (2024):
    AAPL, MSFT, AMZN, NVDA, META, GOOGL, GOOG, AVGO, TSLA, COST

  SOXX (半导体指数) 前十大持仓 (2024):  
    NVDA, AVGO, AMD, QCOM, TXN, INTC, MU, AMAT, LRCX, KLAC

  重叠:
    ✅ NVDA — QQQ 第4大 + SOXX 第1大
    ✅ AVGO — QQQ 第8大 + SOXX 第2大
    ❌ AMD, QCOM, TXN, INTC, MU, AMAT, LRCX, KLAC — 只在 SOXX
    ❌ AAPL, MSFT, AMZN, META, GOOGL, TSLA — 只在 QQQ

  结论:
    - SOXX 是 QQQ 的一个 SECTOR SUBSET（半导体子集）
    - 只有 NVDA + AVGO 真正重叠，其余完全不同
    - SOXX 更集中（30 只股 vs QQQ 100 只），波动更大
    - SOXX 受芯片周期影响，QQQ 受整个科技板块影响
""")

print("=" * 80)
print("SUMMARY")
print("=" * 80)
