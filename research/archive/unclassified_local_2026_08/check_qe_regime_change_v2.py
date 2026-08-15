"""
更严格的 Regime Change 检验
===========================
针对之前分析的三个改进:
1. 让数据自己找断点（不预设2009）
2. 补齐缺失的 p-value（HYG/IEF, 年化收益）
3. 多断点搜索 — 是不是只有2009？
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

dr_qqq = qqq.pct_change().dropna()

# ============================================================================
print("=" * 80)
print("IMPROVEMENT 1: 让数据自己找断点")
print("Sliding Chow-style test — 在每个可能的断点上比较两段的波动率和均值")
print("=" * 80)

# Use QQQ daily returns, test every possible breakpoint
# For each breakpoint, compute Levene test (variance) and t-test (mean)
# Find the breakpoint that maximizes the test statistic

min_window = 252  # at least 1 year on each side
results = []

for i in range(min_window, len(dr_qqq) - min_window):
    date = dr_qqq.index[i]
    pre = dr_qqq.iloc[:i]
    post = dr_qqq.iloc[i:]
    
    # Levene test for variance
    lev_stat, lev_p = stats.levene(pre, post)
    # t-test for mean
    t_stat, t_p = stats.ttest_ind(pre, post)
    # KS test for distribution
    ks_stat, ks_p = stats.ks_2samp(pre, post)
    
    results.append({
        'date': date, 'idx': i,
        'lev_stat': lev_stat, 'lev_p': lev_p,
        't_stat': t_stat, 't_p': t_p,
        'ks_stat': ks_stat, 'ks_p': ks_p,
    })

res_df = pd.DataFrame(results).set_index('date')

# Find the breakpoint that maximizes each test statistic
best_levene = res_df['lev_stat'].idxmax()
best_ttest = res_df['t_stat'].abs().idxmax()
best_ks = res_df['ks_stat'].idxmax()

print(f"\n  QQQ daily returns: {dr_qqq.index[0].date()} → {dr_qqq.index[-1].date()} ({len(dr_qqq)} days)")
print(f"\n  数据自动找到的最优断点:")
print(f"    Levene (波动率):  {best_levene.date()}  F={res_df.loc[best_levene, 'lev_stat']:.2f}  p={res_df.loc[best_levene, 'lev_p']:.6f}")
print(f"    t-test (均值):   {best_ttest.date()}  t={res_df.loc[best_ttest, 't_stat']:.2f}  p={res_df.loc[best_ttest, 't_p']:.6f}")
print(f"    KS (分布):       {best_ks.date()}  stat={res_df.loc[best_ks, 'ks_stat']:.4f}  p={res_df.loc[best_ks, 'ks_p']:.6f}")

# Top 5 breakpoints for each
print(f"\n  --- Levene (波动率差异) Top 5 断点 ---")
top_lev = res_df.nlargest(5, 'lev_stat')
for date, row in top_lev.iterrows():
    print(f"    {date.date()}  F={row['lev_stat']:.2f}  p={row['lev_p']:.6f}")

print(f"\n  --- KS (分布差异) Top 5 断点 ---")
top_ks = res_df.nlargest(5, 'ks_stat')
for date, row in top_ks.iterrows():
    print(f"    {date.date()}  stat={row['ks_stat']:.4f}  p={row['ks_p']:.6f}")

# Where does 2009-03-09 rank?
target = pd.Timestamp('2009-03-09')
closest_target = res_df.index[res_df.index.get_indexer([target], method='nearest')[0]]
rank_lev = (res_df['lev_stat'] > res_df.loc[closest_target, 'lev_stat']).sum() + 1
rank_ks = (res_df['ks_stat'] > res_df.loc[closest_target, 'ks_stat']).sum() + 1
total = len(res_df)
print(f"\n  2009-03-09 在所有断点中的排名:")
print(f"    Levene: #{rank_lev}/{total} (top {rank_lev/total*100:.1f}%)")
print(f"    KS:     #{rank_ks}/{total} (top {rank_ks/total*100:.1f}%)")

# ============================================================================
print("\n")
print("=" * 80)
print("IMPROVEMENT 2: 补齐缺失的 p-value")
print("=" * 80)

BREAK = pd.Timestamp('2009-03-09')

# --- HYG/IEF volatility formal test ---
print(f"\n  --- HYG/IEF 波动率正式检验 ---")
common = hyg.index.intersection(ief.index)
ratio = (hyg.reindex(common) / ief.reindex(common))
ratio_dr = ratio.pct_change().dropna()

pre_ratio = ratio_dr[ratio_dr.index < BREAK]
post_ratio = ratio_dr[ratio_dr.index >= BREAK]

if len(pre_ratio) > 20:
    lev_stat, lev_p = stats.levene(pre_ratio, post_ratio)
    print(f"    Pre-QE  vol: {pre_ratio.std()*np.sqrt(252)*100:.1f}% (n={len(pre_ratio)})")
    print(f"    Post-QE vol: {post_ratio.std()*np.sqrt(252)*100:.1f}% (n={len(post_ratio)})")
    print(f"    Levene test: F={lev_stat:.2f}, p={lev_p:.6f}")
    
    # F-test for variance ratio
    f_stat = pre_ratio.var() / post_ratio.var()
    f_p = 1 - stats.f.cdf(f_stat, len(pre_ratio)-1, len(post_ratio)-1)
    print(f"    F-test (variance ratio): F={f_stat:.2f}, p={f_p:.6f}")
else:
    print(f"    Pre-QE 数据太少 (n={len(pre_ratio)}), HYG 从 2007-04 才有数据")
    print(f"    改用 2007-04 到 2009-03 vs 2009-03+ 来测试")
    # Even with shorter pre-period
    lev_stat, lev_p = stats.levene(pre_ratio, post_ratio)
    print(f"    Pre  vol: {pre_ratio.std()*np.sqrt(252)*100:.1f}% (n={len(pre_ratio)})")
    print(f"    Post vol: {post_ratio.std()*np.sqrt(252)*100:.1f}% (n={len(post_ratio)})")
    print(f"    Levene test: F={lev_stat:.2f}, p={lev_p:.6f}")

# --- Annual return formal test ---
print(f"\n  --- 年化收益正式检验 ---")
pre_dr = dr_qqq[dr_qqq.index < BREAK]
post_dr = dr_qqq[dr_qqq.index >= BREAK]

# Welch's t-test on daily mean returns
t_stat, t_p = stats.ttest_ind(pre_dr, post_dr, equal_var=False)
print(f"    Pre-QE  daily mean: {pre_dr.mean()*252*100:.1f}% annualized (n={len(pre_dr)})")
print(f"    Post-QE daily mean: {post_dr.mean()*252*100:.1f}% annualized (n={len(post_dr)})")
print(f"    Welch's t-test: t={t_stat:.2f}, p={t_p:.6f}")

# Bootstrap test for robustness
print(f"\n  --- Bootstrap 95% CI for mean difference ---")
np.random.seed(42)
n_boot = 10000
boot_diffs = []
combined = dr_qqq.values
n_pre = len(pre_dr)
for _ in range(n_boot):
    idx = np.random.choice(len(combined), len(combined), replace=True)
    boot_pre = combined[idx[:n_pre]]
    boot_post = combined[idx[n_pre:]]
    boot_diffs.append(boot_post.mean() - boot_pre.mean())
boot_diffs = np.array(boot_diffs)
ci_low, ci_high = np.percentile(boot_diffs, [2.5, 97.5])
actual_diff = post_dr.mean() - pre_dr.mean()
print(f"    Actual difference: {actual_diff*252*100:.2f}% annualized")
print(f"    Bootstrap 95% CI: [{ci_low*252*100:.2f}%, {ci_high*252*100:.2f}%]")
print(f"    Zero in CI? {'YES → not significant' if ci_low <= 0 <= ci_high else 'NO → significant'}")

# ============================================================================
print("\n")
print("=" * 80)
print("IMPROVEMENT 3: 多时间尺度 — 滚动窗口里的 regime 特征")
print("=" * 80)

# Rolling 252d volatility and Sharpe, with regime coloring
roll_vol = dr_qqq.rolling(252).std() * np.sqrt(252)
roll_mean = dr_qqq.rolling(252).mean() * 252
roll_sharpe = roll_mean / (roll_vol + 1e-10)

# Calculate statistics for different sub-periods
periods = [
    ("2003-2007 (Pre-crisis)", '2003-01-01', '2007-10-01'),
    ("2007-2009 (GFC)", '2007-10-01', '2009-03-09'),
    ("2009-2012 (QE1-2)", '2009-03-09', '2012-12-31'),
    ("2013-2018 (QE3 + taper)", '2013-01-01', '2018-12-31'),
    ("2019-2020 (COVID)", '2019-01-01', '2020-12-31'),
    ("2021-2022 (Inflation + hikes)", '2021-01-01', '2022-12-31'),
    ("2023-2026 (Post-hike)", '2023-01-01', '2026-12-31'),
]

print(f"\n  {'Period':<35s} {'Vol':>7s} {'Return':>8s} {'Sharpe':>8s} {'Skew':>7s} {'Kurt':>7s} {'n':>6s}")
print(f"  {'-'*35:<35s} {'-'*7:>7s} {'-'*8:>8s} {'-'*8:>8s} {'-'*7:>7s} {'-'*7:>7s} {'-'*6:>6s}")

for label, start, end in periods:
    mask = (dr_qqq.index >= pd.Timestamp(start)) & (dr_qqq.index < pd.Timestamp(end))
    if mask.sum() < 20:
        continue
    sub = dr_qqq[mask]
    vol = sub.std() * np.sqrt(252)
    ret = sub.mean() * 252
    sharpe = ret / vol if vol > 0 else 0
    skew = sub.skew()
    kurt = sub.kurtosis()
    print(f"  {label:<35s} {vol*100:>6.1f}% {ret*100:>+7.1f}% {sharpe:>7.2f} {skew:>+6.2f} {kurt:>6.1f} {mask.sum():>5d}")

# ============================================================================
print("\n")
print("=" * 80)
print("IMPROVEMENT 4: 是否2009是唯一合理断点？")
print("=" * 80)

# Test multiple candidate breakpoints
candidates = [
    ("2007-10 GFC start", '2007-10-01'),
    ("2008-11 QE1 announced", '2008-11-25'),
    ("2009-03 Market bottom", '2009-03-09'),
    ("2010-11 QE2 announced", '2010-11-03'),
    ("2012-09 QE3 announced", '2012-09-13'),
    ("2020-03 COVID QE", '2020-03-23'),
]

print(f"\n  {'Candidate Break':<30s} {'Levene F':>10s} {'p':>10s} {'KS stat':>10s} {'p':>10s}")
print(f"  {'-'*30:<30s} {'-'*10:>10s} {'-'*10:>10s} {'-'*10:>10s} {'-'*10:>10s}")

for label, date_str in candidates:
    bp = pd.Timestamp(date_str)
    pre = dr_qqq[dr_qqq.index < bp]
    post = dr_qqq[dr_qqq.index >= bp]
    if len(pre) < 100 or len(post) < 100:
        continue
    lev_s, lev_p = stats.levene(pre, post)
    ks_s, ks_p = stats.ks_2samp(pre, post)
    print(f"  {label:<30s} {lev_s:>9.2f} {lev_p:>10.6f} {ks_s:>9.4f} {ks_p:>10.6f}")

# ============================================================================
print("\n")
print("=" * 80)
print("REVISED VERDICT — 更诚实的证据分级")
print("=" * 80)
