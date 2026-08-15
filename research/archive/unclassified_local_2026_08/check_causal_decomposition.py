"""
因果机制分解：为什么 2009 后市场"变了"？
==========================================
不问"变没变"，问"通过什么路径变的，各贡献多少？"

四条候选因果链：
A) QE → 实际利率↓ → 估值↑ → 收益↑
B) GFC结束 → 信用修复 → 信用波动↓
C) 科技盈利爆发 → QQQ 基本面↑
D) 市场结构变化 → 波动↓

检验方法：
1. 逐段验证每条链的中间环节
2. 资产对照（利率敏感 vs 不敏感）
3. QE 事件日效应
4. QT 是否反转
"""
import os
import numpy as np
import pandas as pd
from scipy import stats

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'market_data')

def load_yahoo(name):
    s = pd.read_csv(os.path.join(DATA, f'yahoo_{name}.csv'), index_col=0, parse_dates=True).squeeze()
    return s[~s.index.duplicated(keep='last')].dropna()

def load_fred(name):
    s = pd.read_csv(os.path.join(DATA, f'fred_{name}.csv'), index_col=0, parse_dates=True).squeeze()
    return s[~s.index.duplicated(keep='last')].dropna()

# Load everything
qqq = load_yahoo('QQQ')
spy = load_yahoo('SPY')
iwm = load_yahoo('IWM')  # small cap (less tech)
xlu = load_yahoo('XLU')  # utilities (rate sensitive, no tech)
xlp = load_yahoo('XLP')  # staples (defensive, no tech)
xly = load_yahoo('XLY')  # consumer disc (has AMZN/TSLA)
vnq = load_yahoo('VNQ')  # REITs (rate sensitive, no tech)
gld = load_yahoo('GLD')  # gold

real_rate_5 = load_fred('DFII5')    # 5Y real rate
real_rate_10 = load_fred('DFII10')  # 10Y real rate
inf_exp = load_fred('T10YIE')       # 10Y breakeven inflation
t5yifr = load_fred('T5YIFR')       # 5Y5Y forward inflation
walcl = load_fred('WALCL')          # Fed balance sheet
dff = load_fred('DFF')              # Fed funds rate

# PE ratio
pe = pd.read_csv(os.path.join(DATA, 'multpl_pe_monthly.csv'), index_col=0, parse_dates=True).squeeze()

# Earnings
earnings = pd.read_csv(os.path.join(DATA, 'multpl_earnings_growth.csv'), index_col=0, parse_dates=True).squeeze()

BREAK = pd.Timestamp('2009-03-09')

# ============================================================================
print("=" * 80)
print("CHAIN A: QE → 实际利率↓ → 估值↑ → 收益↑")
print("=" * 80)

# Step 1: QE → Real rates
print(f"\n  Step 1: QE 后实际利率下降了吗？")
rr5_pre = real_rate_5[real_rate_5.index < BREAK]
rr5_post = real_rate_5[(real_rate_5.index >= BREAK) & (real_rate_5.index < '2022-01-01')]  # exclude hike era
rr5_hike = real_rate_5[real_rate_5.index >= '2022-01-01']

print(f"    5Y Real Rate:")
print(f"      Pre-QE (2003-2009):  mean={rr5_pre.mean():.2f}%  median={rr5_pre.median():.2f}%")
print(f"      QE era (2009-2021):  mean={rr5_post.mean():.2f}%  median={rr5_post.median():.2f}%")
print(f"      Hike era (2022+):    mean={rr5_hike.mean():.2f}%  median={rr5_hike.median():.2f}%")
t, p = stats.ttest_ind(rr5_pre, rr5_post)
print(f"      Pre vs QE t-test: t={t:.2f}, p={p:.6f}")
print(f"      → {'✅ 显著下降' if p < 0.05 and t > 0 else '❌ 不显著'}")

# Step 2: Real rates → PE ratio
print(f"\n  Step 2: 低利率推高了估值吗？")
# Align PE with real rates (monthly)
rr_monthly = real_rate_5.resample('MS').mean()
pe_aligned = pe.reindex(rr_monthly.index, method='ffill')
combo = pd.DataFrame({'rr': rr_monthly, 'pe': pe_aligned}).dropna()

pre_combo = combo[combo.index < BREAK]
post_combo = combo[(combo.index >= BREAK) & (combo.index < '2022-01-01')]

print(f"    S&P 500 PE ratio:")
print(f"      Pre-QE:  mean={pre_combo['pe'].mean():.1f}")
print(f"      QE era:  mean={post_combo['pe'].mean():.1f}")

# Correlation between real rates and PE
r_pre = pre_combo['rr'].corr(pre_combo['pe'])
r_post = post_combo['rr'].corr(post_combo['pe'])
r_all = combo['rr'].corr(combo['pe'])
print(f"    Real Rate vs PE correlation:")
print(f"      Pre-QE:  r = {r_pre:.3f}")
print(f"      QE era:  r = {r_post:.3f}")
print(f"      Full:    r = {r_all:.3f}")
print(f"      → {'✅ 负相关（低利率→高估值）' if r_all < -0.3 else '⚠️ 相关性不强'}")

# Step 3: PE expansion → returns
print(f"\n  Step 3: 估值扩张贡献了多少收益？")
pe_start_pre = pe[pe.index >= '2003-01-01'].iloc[0] if len(pe[pe.index >= '2003-01-01']) > 0 else np.nan
pe_end_pre = pe[pe.index < BREAK].iloc[-1] if len(pe[pe.index < BREAK]) > 0 else np.nan
pe_start_post = pe[pe.index >= BREAK].iloc[0] if len(pe[pe.index >= BREAK]) > 0 else np.nan
pe_end_post = pe.iloc[-1]

print(f"    Pre-QE:  PE {pe_start_pre:.1f} → {pe_end_pre:.1f} (change: {(pe_end_pre/pe_start_pre-1)*100:+.1f}%)")
print(f"    Post-QE: PE {pe_start_post:.1f} → {pe_end_post:.1f} (change: {(pe_end_post/pe_start_post-1)*100:+.1f}%)")

# ============================================================================
print("\n")
print("=" * 80)
print("CHAIN B: GFC结束 → 信用修复 → 信用波动↓")
print("=" * 80)

hy_oas = load_fred('BAMLH0A0HYM2')  # HY OAS spread

hy_pre = hy_oas[(hy_oas.index >= '2003-01-01') & (hy_oas.index < BREAK)]
hy_post = hy_oas[(hy_oas.index >= BREAK) & (hy_oas.index < '2020-01-01')]  # before COVID
hy_post_all = hy_oas[hy_oas.index >= BREAK]

print(f"\n  HY OAS Credit Spread (bp):")
print(f"    Pre-QE:        mean={hy_pre.mean()*100:.0f}bp  max={hy_pre.max()*100:.0f}bp")
print(f"    QE (pre-COVID): mean={hy_post.mean()*100:.0f}bp  max={hy_post.max()*100:.0f}bp")
print(f"    QE (all):       mean={hy_post_all.mean()*100:.0f}bp  max={hy_post_all.max()*100:.0f}bp")

# Volatility of credit spreads
hy_dr_pre = hy_pre.pct_change().dropna()
hy_dr_post = hy_post.pct_change().dropna()
lev_s, lev_p = stats.levene(hy_dr_pre, hy_dr_post)
print(f"\n  HY OAS 日变化波动率:")
print(f"    Pre-QE:  {hy_dr_pre.std()*np.sqrt(252)*100:.1f}%")
print(f"    Post-QE: {hy_dr_post.std()*np.sqrt(252)*100:.1f}%")
print(f"    Levene test: F={lev_s:.2f}, p={lev_p:.6f}")
print(f"    → {'✅ 信用波动显著下降' if lev_p < 0.05 else '❌ 不显著'}")

# Is this QE or just crisis ending?
hy_post_2012 = hy_oas[(hy_oas.index >= '2012-01-01') & (hy_oas.index < '2020-01-01')]
print(f"\n  去掉 2009-2011 过渡期后 (2012-2019):")
print(f"    mean={hy_post_2012.mean()*100:.0f}bp — 比 Pre-QE 的 {hy_pre.mean()*100:.0f}bp 低很多")
print(f"    → 说明不只是危机结束，信用利差结构性下移")

# ============================================================================
print("\n")
print("=" * 80)
print("CHAIN C: 科技盈利爆发 → QQQ 基本面↑")
print("=" * 80)

# QQQ vs SPY vs IWM relative performance
print(f"\n  科技股（QQQ）vs 大盘（SPY）vs 小盘（IWM）年化收益:")
for name, etf in [('QQQ', qqq), ('SPY', spy), ('IWM', iwm), ('XLU', xlu), ('XLP', xlp)]:
    pre = etf[(etf.index >= '2003-01-01') & (etf.index < BREAK)]
    post = etf[(etf.index >= BREAK)]
    if len(pre) > 100 and len(post) > 100:
        pre_cagr = (pre.iloc[-1]/pre.iloc[0])**(252/len(pre)) - 1
        post_cagr = (post.iloc[-1]/post.iloc[0])**(252/len(post)) - 1
        print(f"    {name:>5s}:  Pre={pre_cagr*100:>+6.1f}%  Post={post_cagr*100:>+6.1f}%  Diff={((post_cagr-pre_cagr)*100):>+6.1f}pp")

print(f"\n  QQQ 的超额改善是否只是因为科技权重？")
print(f"  如果所有资产都改善相似幅度 → 不只是科技，是系统性的")
print(f"  如果只有 QQQ 改善 → 是科技特有的")

# ============================================================================
print("\n")
print("=" * 80)
print("CHAIN D: 资产对照 — 利率敏感 vs 不敏感")
print("=" * 80)

print(f"\n  理论：如果 QE (低利率) 是主因，那利率敏感资产应该改善更多")
print(f"  利率敏感：VNQ(REITs), XLU(公用事业), TLT(长债)")
print(f"  不敏感：XLP(必需消费), IWM(小盘), GLD(黄金)")

dr_all = pd.DataFrame({
    'QQQ': qqq.pct_change(),
    'SPY': spy.pct_change(),
    'IWM': iwm.pct_change(),
    'XLU': xlu.pct_change(),
    'XLP': xlp.pct_change(),
    'VNQ': vnq.pct_change(),
    'GLD': gld.pct_change(),
}).dropna()

pre_dr = dr_all[dr_all.index < BREAK]
post_dr = dr_all[(dr_all.index >= BREAK) & (dr_all.index < '2022-01-01')]

print(f"\n  {'Asset':<8s} {'Pre Vol':>10s} {'Post Vol':>10s} {'Vol Change':>12s} {'Pre Sharpe':>12s} {'Post Sharpe':>12s}")
print(f"  {'-'*8:<8s} {'-'*10:>10s} {'-'*10:>10s} {'-'*12:>12s} {'-'*12:>12s} {'-'*12:>12s}")

for col in ['QQQ', 'SPY', 'IWM', 'XLU', 'XLP', 'VNQ', 'GLD']:
    pre_vol = pre_dr[col].std() * np.sqrt(252)
    post_vol = post_dr[col].std() * np.sqrt(252)
    pre_sharpe = pre_dr[col].mean() / pre_dr[col].std() * np.sqrt(252) if pre_dr[col].std() > 0 else 0
    post_sharpe = post_dr[col].mean() / post_dr[col].std() * np.sqrt(252) if post_dr[col].std() > 0 else 0
    vol_change = (post_vol / pre_vol - 1) * 100
    print(f"  {col:<8s} {pre_vol*100:>9.1f}% {post_vol*100:>9.1f}% {vol_change:>+11.1f}% {pre_sharpe:>11.2f} {post_sharpe:>11.2f}")

# ============================================================================
print("\n")
print("=" * 80)
print("TEST: QE 事件日效应 — QE 宣布当天发生了什么？")
print("=" * 80)

qe_events = [
    ("QE1 announced", '2008-11-25'),
    ("QE1 expanded", '2009-03-18'),
    ("QE2 announced", '2010-11-03'),
    ("Operation Twist", '2011-09-21'),
    ("QE3 announced", '2012-09-13'),
    ("Taper tantrum", '2013-05-22'),
    ("QE3 taper starts", '2013-12-18'),
    ("QE3 ends", '2014-10-29'),
    ("COVID QE", '2020-03-23'),
    ("QT1 starts", '2017-10-01'),
    ("QT2 starts", '2022-06-01'),
]

dr_qqq = qqq.pct_change()
rr10 = real_rate_10

print(f"\n  {'Event':<25s} {'QQQ 1d':>8s} {'QQQ 5d':>8s} {'RealRate chg':>13s}")
print(f"  {'-'*25:<25s} {'-'*8:>8s} {'-'*8:>8s} {'-'*13:>13s}")

for label, date_str in qe_events:
    dt = pd.Timestamp(date_str)
    # Find nearest trading day
    qqq_idx = dr_qqq.index
    nearest = qqq_idx[qqq_idx.get_indexer([dt], method='nearest')[0]]
    pos = qqq_idx.get_loc(nearest)
    
    r1d = dr_qqq.iloc[pos] if pos < len(dr_qqq) else np.nan
    r5d = (qqq.iloc[min(pos+5, len(qqq)-1)] / qqq.iloc[pos] - 1) if pos < len(qqq) - 5 else np.nan
    
    # Real rate change
    rr_idx = rr10.index
    rr_nearest = rr_idx[rr_idx.get_indexer([dt], method='nearest')[0]]
    rr_pos = rr_idx.get_loc(rr_nearest)
    rr_chg = rr10.iloc[min(rr_pos+5, len(rr10)-1)] - rr10.iloc[rr_pos] if rr_pos < len(rr10) - 5 else np.nan
    
    print(f"  {label:<25s} {r1d*100:>+7.2f}% {r5d*100:>+7.2f}% {rr_chg:>+12.2f}bp" if not np.isnan(rr_chg) 
          else f"  {label:<25s} {r1d*100:>+7.2f}% {r5d*100:>+7.2f}% {'N/A':>13s}")

# ============================================================================
print("\n")
print("=" * 80)
print("TEST: QT 是否反转了 QE 的效果？")
print("=" * 80)

# Compare QE periods vs QT periods
periods = [
    ("QE1-3 (2009-2014)", '2009-03-09', '2014-10-29'),
    ("QT pause (2015-2017)", '2015-01-01', '2017-09-30'),
    ("QT1 (2017-2019)", '2017-10-01', '2019-07-31'),
    ("COVID QE (2020-2021)", '2020-03-23', '2021-12-31'),
    ("QT2 (2022-now)", '2022-06-01', '2026-12-31'),
]

print(f"\n  {'Period':<30s} {'QQQ CAGR':>10s} {'QQQ Vol':>9s} {'Sharpe':>8s} {'5Y Real':>8s} {'WALCL chg':>10s}")
print(f"  {'-'*30:<30s} {'-'*10:>10s} {'-'*9:>9s} {'-'*8:>8s} {'-'*8:>8s} {'-'*10:>10s}")

for label, start, end in periods:
    mask = (qqq.index >= pd.Timestamp(start)) & (qqq.index <= pd.Timestamp(end))
    q = qqq[mask]
    if len(q) < 50:
        continue
    
    cagr = (q.iloc[-1]/q.iloc[0])**(252/len(q)) - 1
    dr = q.pct_change().dropna()
    vol = dr.std() * np.sqrt(252)
    sharpe = dr.mean()/dr.std()*np.sqrt(252) if dr.std() > 0 else 0
    
    rr_mask = (real_rate_5.index >= pd.Timestamp(start)) & (real_rate_5.index <= pd.Timestamp(end))
    rr_mean = real_rate_5[rr_mask].mean() if rr_mask.sum() > 0 else np.nan
    
    w_mask = (walcl.index >= pd.Timestamp(start)) & (walcl.index <= pd.Timestamp(end))
    w = walcl[w_mask]
    w_chg = ((w.iloc[-1]/w.iloc[0])**(52/len(w))-1)*100 if len(w) > 2 else np.nan
    
    rr_str = f"{rr_mean:>+7.2f}%" if not np.isnan(rr_mean) else "  N/A"
    w_str = f"{w_chg:>+8.1f}%/yr" if not np.isnan(w_chg) else "  N/A"
    print(f"  {label:<30s} {cagr*100:>+9.1f}% {vol*100:>8.1f}% {sharpe:>7.2f} {rr_str} {w_str}")

# ============================================================================
print("\n")
print("=" * 80)
print("REGRESSION: 实际利率变化能解释多少 QQQ 收益变化？")
print("=" * 80)

# Monthly regression: QQQ return ~ real rate change + earnings growth + credit spread change
qqq_monthly = qqq.resample('MS').last().pct_change()
rr_monthly = real_rate_5.resample('MS').last().diff()
hy_monthly = hy_oas.resample('MS').last().diff()

reg_data = pd.DataFrame({
    'qqq_ret': qqq_monthly,
    'rr_chg': rr_monthly,
    'hy_chg': hy_monthly,
}).dropna()

# Simple OLS
from numpy.linalg import lstsq

X = reg_data[['rr_chg', 'hy_chg']].values
X = np.column_stack([X, np.ones(len(X))])
y = reg_data['qqq_ret'].values

betas, residuals, _, _ = lstsq(X, y, rcond=None)
y_pred = X @ betas
ss_res = np.sum((y - y_pred)**2)
ss_tot = np.sum((y - y.mean())**2)
r_squared = 1 - ss_res/ss_tot

print(f"\n  Monthly regression: QQQ_ret ~ β1·Δ(RealRate) + β2·Δ(HY_OAS) + c")
print(f"    β(Real Rate): {betas[0]:.4f}  (negative = lower rates help)")
print(f"    β(HY OAS):    {betas[1]:.4f}  (negative = tighter spreads help)")
print(f"    Intercept:    {betas[2]:.4f}")
print(f"    R²:           {r_squared:.4f}")
print(f"    n:            {len(reg_data)}")

# Split by regime
for label, start, end in [("Pre-QE", '2003-01-01', '2009-03-01'),
                           ("QE era", '2009-03-01', '2022-01-01'),
                           ("Hike era", '2022-01-01', '2027-01-01')]:
    mask = (reg_data.index >= pd.Timestamp(start)) & (reg_data.index < pd.Timestamp(end))
    sub = reg_data[mask]
    if len(sub) < 12:
        continue
    X_s = sub[['rr_chg', 'hy_chg']].values
    X_s = np.column_stack([X_s, np.ones(len(X_s))])
    y_s = sub['qqq_ret'].values
    b, _, _, _ = lstsq(X_s, y_s, rcond=None)
    y_p = X_s @ b
    r2 = 1 - np.sum((y_s - y_p)**2) / np.sum((y_s - y_s.mean())**2)
    print(f"\n    {label}: β(RR)={b[0]:.4f}, β(HY)={b[1]:.4f}, R²={r2:.4f}, n={len(sub)}")

# ============================================================================
print("\n")
print("=" * 80)
print("DECOMPOSITION: 各因素贡献估计")
print("=" * 80)
