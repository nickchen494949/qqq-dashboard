"""
科学验证：2009 QE 是否构成结构性质变？
========================================
测试：
1. 崩盘后的恢复速度 — 有 Fed Put 后是否 V 型更快？
2. 信用利差行为变化 — HYG/IEF 的波动模式是否不同？
3. VIX 均值回归速度 — Fed Put 是否让恐慌消退更快？
4. QQQ 回报分布 — 尾部风险是否变了？
5. Fed 资产负债表 vs 股市相关性 — QE 前后是否不同？
"""
import os
import numpy as np
import pandas as pd
from scipy import stats

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'market_data')

def load(name):
    s = pd.read_csv(os.path.join(DATA, f'yahoo_{name}.csv'), index_col=0, parse_dates=True).squeeze()
    return s[~s.index.duplicated(keep='last')].dropna()

qqq = load('QQQ')
hyg = load('HYG')
ief = load('IEF')
spy = load('SPY')

vix = pd.read_csv(os.path.join(DATA, 'fred_VIXCLS.csv'), index_col=0, parse_dates=True).squeeze().dropna()
walcl = pd.read_csv(os.path.join(DATA, 'fred_WALCL.csv'), index_col=0, parse_dates=True).squeeze().dropna()

# Define regimes
BREAK = pd.Timestamp('2009-03-09')  # QE1 announced Nov 2008, market bottom Mar 2009
PRE = 'Pre-QE (2003-2009)'
POST = 'Post-QE (2009-2026)'

dr_qqq = qqq.pct_change().dropna()

print("=" * 80)
print("TEST 1: 崩盘后恢复速度 — V 型反弹是 QE 特有的吗？")
print("=" * 80)

# Find all drawdowns > 15% and measure recovery time
peak_val = qqq.expanding().max()
dd = qqq / peak_val - 1

# Find trough points of significant drawdowns
episodes = []
in_dd = False
for date, val in dd.items():
    if not in_dd and val < -0.15:
        peak_date = qqq.loc[:date].idxmax()
        in_dd = True
        trough = val; trough_date = date
    elif in_dd:
        if val < trough:
            trough = val; trough_date = date
        if val > -0.05:  # recovered to within 5%
            recovery_days = (date - trough_date).days
            episodes.append({
                'peak': peak_date, 'trough': trough_date,
                'recovery': date, 'dd': trough,
                'recovery_days': recovery_days,
                'regime': PRE if trough_date < BREAK else POST
            })
            in_dd = False

print(f"\n{'Peak Date':<14s} {'Trough Date':<14s} {'DD':>7s} {'Recovery Days':>14s} {'Regime':<25s}")
print("-" * 80)
for ep in episodes:
    print(f"{ep['peak'].date()!s:<14s} {ep['trough'].date()!s:<14s} {ep['dd']*100:>+6.1f}% "
          f"{ep['recovery_days']:>13d}d {ep['regime']:<25s}")

pre_recovery = [e['recovery_days'] for e in episodes if e['regime'] == PRE]
post_recovery = [e['recovery_days'] for e in episodes if e['regime'] == POST]
print(f"\n  Pre-QE  平均恢复: {np.mean(pre_recovery):.0f} 天 (n={len(pre_recovery)})")
print(f"  Post-QE 平均恢复: {np.mean(post_recovery):.0f} 天 (n={len(post_recovery)})")
if len(pre_recovery) > 0 and len(post_recovery) > 1:
    t, p = stats.mannwhitneyu(pre_recovery, post_recovery, alternative='greater')
    print(f"  Mann-Whitney U test (pre > post): p = {p:.4f}")

# ============================================================================
print("\n")
print("=" * 80)
print("TEST 2: QQQ 日收益率分布 — 尾部风险变了吗？")
print("=" * 80)

pre_dr = dr_qqq[dr_qqq.index < BREAK]
post_dr = dr_qqq[dr_qqq.index >= BREAK]

print(f"\n{'Metric':<25s} {'Pre-QE':>12s} {'Post-QE':>12s}")
print("-" * 55)
print(f"{'观测天数':<25s} {len(pre_dr):>12d} {len(post_dr):>12d}")
print(f"{'年化波动率':<25s} {pre_dr.std()*np.sqrt(252)*100:>11.1f}% {post_dr.std()*np.sqrt(252)*100:>11.1f}%")
print(f"{'年化收益率':<25s} {pre_dr.mean()*252*100:>11.1f}% {post_dr.mean()*252*100:>11.1f}%")
print(f"{'偏度 (skewness)':<25s} {pre_dr.skew():>12.3f} {post_dr.skew():>12.3f}")
print(f"{'峰度 (kurtosis)':<25s} {pre_dr.kurtosis():>12.3f} {post_dr.kurtosis():>12.3f}")
print(f"{'最大单日跌幅':<25s} {pre_dr.min()*100:>11.2f}% {post_dr.min()*100:>11.2f}%")
print(f"{'跌>3% 的天数占比':<25s} {(pre_dr < -0.03).mean()*100:>11.2f}% {(post_dr < -0.03).mean()*100:>11.2f}%")
print(f"{'跌>5% 的天数占比':<25s} {(pre_dr < -0.05).mean()*100:>11.2f}% {(post_dr < -0.05).mean()*100:>11.2f}%")

# Levene's test for equality of variances
stat, p = stats.levene(pre_dr, post_dr)
print(f"\n  Levene's test (方差齐性): F={stat:.2f}, p={p:.4f}")
if p < 0.05:
    print(f"  → 方差显著不同 (p < 0.05)")

# ============================================================================
print("\n")
print("=" * 80)
print("TEST 3: VIX 均值回归速度 — Fed Put 让恐慌消退更快？")
print("=" * 80)

# Find VIX spikes > 30, measure days to return below 20
vix_spikes = []
in_spike = False
for date, val in vix.items():
    if not in_spike and val > 30:
        spike_start = date
        spike_peak = val
        in_spike = True
    elif in_spike:
        if val > spike_peak:
            spike_peak = val
        if val < 20:
            duration = (date - spike_start).days
            vix_spikes.append({
                'start': spike_start, 'end': date,
                'peak': spike_peak, 'duration': duration,
                'regime': PRE if spike_start < BREAK else POST
            })
            in_spike = False

print(f"\n{'Spike Start':<14s} {'Peak VIX':>10s} {'Days to <20':>13s} {'Regime':<25s}")
print("-" * 70)
for sp in vix_spikes:
    print(f"{sp['start'].date()!s:<14s} {sp['peak']:>9.1f} {sp['duration']:>12d}d {sp['regime']:<25s}")

pre_dur = [s['duration'] for s in vix_spikes if s['regime'] == PRE]
post_dur = [s['duration'] for s in vix_spikes if s['regime'] == POST]
if pre_dur:
    print(f"\n  Pre-QE  VIX 恐慌平均持续: {np.mean(pre_dur):.0f} 天 (n={len(pre_dur)})")
if post_dur:
    print(f"  Post-QE VIX 恐慌平均持续: {np.mean(post_dur):.0f} 天 (n={len(post_dur)})")

# ============================================================================
print("\n")
print("=" * 80)
print("TEST 4: HYG/IEF 信用利差行为 — QE 改变了信用市场吗？")
print("=" * 80)

common = hyg.index.intersection(ief.index)
hyg_c = hyg.reindex(common)
ief_c = ief.reindex(common)
ratio = hyg_c / ief_c
ratio_dr = ratio.pct_change().dropna()

pre_ratio = ratio_dr[ratio_dr.index < BREAK]
post_ratio = ratio_dr[ratio_dr.index >= BREAK]

print(f"\n  HYG/IEF 比值日波动率:")
print(f"    Pre-QE:  {pre_ratio.std()*np.sqrt(252)*100:.1f}%")
print(f"    Post-QE: {post_ratio.std()*np.sqrt(252)*100:.1f}%")

# Correlation of HYG/IEF ratio changes with QQQ returns
dr_qqq_c = qqq.reindex(common).pct_change().dropna()
ratio_dr_c = ratio_dr.reindex(dr_qqq_c.index)
valid = pd.DataFrame({'qqq': dr_qqq_c, 'ratio': ratio_dr_c}).dropna()

pre_valid = valid[valid.index < BREAK]
post_valid = valid[valid.index >= BREAK]

print(f"\n  HYG/IEF 与 QQQ 日收益相关性:")
print(f"    Pre-QE:  r = {pre_valid['qqq'].corr(pre_valid['ratio']):.4f}")
print(f"    Post-QE: r = {post_valid['qqq'].corr(post_valid['ratio']):.4f}")

# ============================================================================
print("\n")
print("=" * 80)
print("TEST 5: Fed 资产负债表 vs 股市 — QE 开始后关系变了吗？")
print("=" * 80)

# WALCL is weekly, resample QQQ to weekly
qqq_weekly = qqq.resample('W').last().dropna()
walcl_w = walcl.reindex(qqq_weekly.index, method='ffill').dropna()
common_w = qqq_weekly.index.intersection(walcl_w.index)

qqq_w = qqq_weekly.reindex(common_w)
walcl_wk = walcl_w.reindex(common_w)

# Rolling 52-week correlation
dr_qqq_w = qqq_w.pct_change()
dr_walcl_w = walcl_wk.pct_change()

combo = pd.DataFrame({'qqq': dr_qqq_w, 'walcl': dr_walcl_w}).dropna()

pre_combo = combo[combo.index < BREAK]
post_combo = combo[combo.index >= BREAK]

if len(pre_combo) > 10:
    print(f"\n  Fed 资产负债表周变化 vs QQQ 周收益相关性:")
    print(f"    Pre-QE:  r = {pre_combo['qqq'].corr(pre_combo['walcl']):.4f} (n={len(pre_combo)})")
if len(post_combo) > 10:
    print(f"    Post-QE: r = {post_combo['qqq'].corr(post_combo['walcl']):.4f} (n={len(post_combo)})")

# Year-by-year correlation
print(f"\n  分年度 WALCL vs QQQ 相关性:")
for year in range(combo.index[0].year, combo.index[-1].year + 1):
    mask = combo.index.year == year
    if mask.sum() < 10:
        continue
    r = combo.loc[mask, 'qqq'].corr(combo.loc[mask, 'walcl'])
    bar = '█' * int(abs(r) * 30)
    sign = '+' if r > 0 else '-'
    print(f"    {year}: r={r:+.3f} {sign}{bar}")

# ============================================================================
print("\n")
print("=" * 80)
print("TEST 6: 结构性断点检验 — Chow Test 思路")
print("=" * 80)

# Simple approach: compare rolling 252d Sharpe ratio distribution
sharpe_roll = dr_qqq.rolling(252).apply(lambda x: x.mean()/x.std()*np.sqrt(252), raw=True)
pre_sharpe = sharpe_roll[(sharpe_roll.index < BREAK)].dropna()
post_sharpe = sharpe_roll[(sharpe_roll.index >= BREAK)].dropna()

print(f"\n  QQQ 滚动 252d Sharpe ratio:")
print(f"    Pre-QE:  mean={pre_sharpe.mean():.2f}, std={pre_sharpe.std():.2f}")
print(f"    Post-QE: mean={post_sharpe.mean():.2f}, std={post_sharpe.std():.2f}")

t_stat, p_val = stats.ttest_ind(pre_sharpe, post_sharpe)
print(f"    t-test: t={t_stat:.2f}, p={p_val:.4f}")

# Kolmogorov-Smirnov test
ks_stat, ks_p = stats.ks_2samp(pre_sharpe, post_sharpe)
print(f"    KS test: stat={ks_stat:.3f}, p={ks_p:.4f}")

print("\n")
print("=" * 80)
print("VERDICT")
print("=" * 80)
