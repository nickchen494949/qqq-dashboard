"""
3M T-Bill > Fed Funds = 市场定价加息 → 能不能预测崩盘？
==========================================================
逻辑：3M > FF → 市场预期 Fed 要加息 → 紧缩 → 风险
跟 SEP EXIT 一样的鹰派逻辑。
"""
import os, sys
import numpy as np
import pandas as pd
import urllib.request, json

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(project_root, 'tools'))
from strategy_engine import get_fred_api_key

api_key = get_fred_api_key()

def fetch_fred(series_id, api_key):
    url = (f"https://api.stlouisfed.org/fred/series/observations"
           f"?series_id={series_id}&api_key={api_key}"
           f"&file_type=json&observation_start=2003-01-01")
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read())
    rows = []
    for obs in data['observations']:
        if obs['value'] != '.':
            rows.append({'date': obs['date'], 'value': float(obs['value'])})
    df = pd.DataFrame(rows)
    df['date'] = pd.to_datetime(df['date'])
    return df.set_index('date').sort_index()

print("Fetching 3-month T-bill (DTB3) from FRED...")
tb3m = fetch_fred('DTB3', api_key)
tb3m.columns = ['TB3M']

# Load local data
dff = pd.read_csv(os.path.join(project_root, 'market_data/fred_DFF.csv'),
                  parse_dates=[0], index_col=0)
dff.columns = ['FF']

qqq = pd.read_csv(os.path.join(project_root, 'market_data/yahoo_QQQ.csv'),
                  parse_dates=['Date']).rename(columns={'Date': 'date'}).set_index('date')

df = qqq[['QQQ']].join(tb3m, how='inner').join(dff, how='inner').dropna()
df['spread'] = df['TB3M'] - df['FF']  # positive = market pricing hikes
df['QQQ_ret'] = df['QQQ'].pct_change()

print(f"Data: {df.index[0].date()} → {df.index[-1].date()} ({len(df)} days)")
print(f"Spread range: {df['spread'].min():.2f} to {df['spread'].max():.2f}")
print()

# ============================================================================
# 找所有 QQQ 崩盘 (>15%)
# ============================================================================
df['peak'] = df['QQQ'].cummax()
df['dd'] = df['QQQ'] / df['peak'] - 1

crashes = []
in_dd = False
for date, row in df.iterrows():
    if not in_dd and row['dd'] < -0.15:
        peak_date = df.loc[:date, 'QQQ'].idxmax()
        in_dd = True
        trough_dd = row['dd']
        trough_date = date
    elif in_dd:
        if row['dd'] < trough_dd:
            trough_dd = row['dd']
            trough_date = date
        if row['dd'] > -0.15 * 0.3:
            crashes.append({'peak': peak_date, 'trough': trough_date, 'dd': trough_dd})
            in_dd = False
if in_dd:
    crashes.append({'peak': peak_date, 'trough': trough_date, 'dd': trough_dd})

# ============================================================================
# PART 1: 加息信号 (3M > FF) vs 崩盘
# ============================================================================
print("=" * 80)
print("PART 1: 3M > FF（市场定价加息）vs QQQ 崩盘")
print("=" * 80)
print()

for thresh_name, thresh in [('+5bp', 0.05), ('+10bp', 0.10), ('+20bp', 0.20), ('+30bp', 0.30)]:
    hawk_days = (df['spread'] > thresh).sum()
    print(f"  3M-FF > {thresh_name}: {hawk_days}d ({hawk_days/len(df)*100:.1f}%)")
print()

for ep in crashes:
    pd_date = ep['peak']
    
    print(f"📉 Peak: {pd_date.date()} → Trough: {ep['trough'].date()}  DD: {ep['dd']*100:.1f}%")
    
    # 看崩盘前各时间窗口的加息信号
    for lb_name, lb_months in [('3mo', 3), ('6mo', 6), ('12mo', 12)]:
        lb_start = pd_date - pd.DateOffset(months=lb_months)
        window = df.loc[lb_start:pd_date]
        if len(window) == 0:
            continue
        
        for thresh_name, thresh in [('>5bp', 0.05), ('>10bp', 0.10), ('>20bp', 0.20)]:
            hawk = (window['spread'] > thresh).sum()
            if thresh == 0.10:
                hawk_10 = hawk
            elif thresh == 0.20:
                hawk_20 = hawk
        
        max_spread = window['spread'].max()
        avg_spread = window['spread'].mean()
        
        if lb_name == '6mo':
            print(f"   Prior {lb_name}: {hawk_10:3d}d >10bp, {hawk_20:3d}d >20bp  "
                  f"max={max_spread:+.3f}  avg={avg_spread:+.3f}  "
                  f"{'✅ HAWK' if hawk_20 > 10 else '❌ no hawk signal'}")
    
    # 时间线
    for offset_name, offset_days in [('-6mo', -183), ('-3mo', -91), ('-1mo', -30), ('Peak', 0)]:
        if offset_days is not None:
            target = pd_date + pd.DateOffset(days=offset_days)
        nearby = df.loc[target - pd.DateOffset(days=3):target + pd.DateOffset(days=3)]
        if len(nearby) > 0:
            r = nearby.iloc[len(nearby)//2]
            print(f"   {offset_name:>6s}: 3M={r['TB3M']:.2f}  FF={r['FF']:.2f}  "
                  f"spread={r['spread']:+.3f}")
    print()

# ============================================================================
# PART 2: 加息幅度 vs 前瞻回报
# ============================================================================
print("=" * 80)
print("PART 2: 前瞻回报 — 加息定价强度 vs QQQ")
print("=" * 80)

for thresh_name, thresh in [('Hiking (>+10bp)', 0.10), ('Strong hiking (>+20bp)', 0.20),
                              ('Aggressive hiking (>+30bp)', 0.30)]:
    hawk = df['spread'] > thresh
    if hawk.sum() < 10:
        continue
    
    print(f"\n  --- {thresh_name} ---")
    for h_name, h_days in [('63d (3mo)', 63), ('126d (6mo)', 126), ('252d (12mo)', 252)]:
        fwd = df['QQQ'].pct_change(h_days).shift(-h_days)
        hawk_fwd = fwd[hawk].dropna()
        norm_fwd = fwd[~hawk].dropna()
        if len(hawk_fwd) == 0:
            continue
        print(f"    {h_name}:")
        print(f"      Normal (n={len(norm_fwd):4d}): mean={norm_fwd.mean()*100:+.1f}%, "
              f"median={norm_fwd.median()*100:+.1f}%, P(<-15%)={100*(norm_fwd<-0.15).mean():.1f}%")
        print(f"      Hawk   (n={len(hawk_fwd):4d}): mean={hawk_fwd.mean()*100:+.1f}%, "
              f"median={hawk_fwd.median()*100:+.1f}%, P(<-15%)={100*(hawk_fwd<-0.15).mean():.1f}%")

# ============================================================================
# PART 3: 加息 z-score（spread 的 rolling z）
# ============================================================================
print("\n")
print("=" * 80)
print("PART 3: Spread Z-Score — 加息加速度信号")
print("=" * 80)

for z_window in [63, 126, 252]:
    spread_z = (df['spread'] - df['spread'].rolling(z_window).mean()) / df['spread'].rolling(z_window).std()
    df[f'spread_z_{z_window}'] = spread_z
    
    print(f"\n  --- Rolling Z-score (window={z_window}d) ---")
    for z_thresh in [1.0, 1.5, 2.0]:
        hawk_z = spread_z > z_thresh
        n = hawk_z.sum()
        if n < 10:
            continue
        
        fwd_252 = df['QQQ'].pct_change(252).shift(-252)
        hawk_fwd = fwd_252[hawk_z].dropna()
        norm_fwd = fwd_252[~hawk_z].dropna()
        
        if len(hawk_fwd) == 0:
            continue
        
        print(f"    Z > {z_thresh}: {n}d ({n/len(df)*100:.1f}%)")
        print(f"      12mo fwd: hawk mean={hawk_fwd.mean()*100:+.1f}%, "
              f"P(<-15%)={100*(hawk_fwd<-0.15).mean():.1f}%  |  "
              f"normal mean={norm_fwd.mean()*100:+.1f}%, "
              f"P(<-15%)={100*(norm_fwd<-0.15).mean():.1f}%")

# ============================================================================
# PART 4: 策略回测 — 加息信号出场
# ============================================================================
print("\n")
print("=" * 80)
print("PART 4: 策略回测 — 3M-FF 加息信号出场")
print("=" * 80)

for thresh_name, thresh in [('>10bp', 0.10), ('>20bp', 0.20), ('>30bp', 0.30)]:
    hawk = df['spread'] > thresh
    strat_ret = df['QQQ_ret'].copy()
    strat_ret[hawk] = 0
    
    bh_cum = (1 + df['QQQ_ret']).cumprod()
    strat_cum = (1 + strat_ret).cumprod()
    
    years = (df.index[-1] - df.index[0]).days / 365.25
    bh_cagr = bh_cum.iloc[-1] ** (1/years) - 1
    strat_cagr = strat_cum.iloc[-1] ** (1/years) - 1
    
    bh_dd = (bh_cum / bh_cum.cummax() - 1).min()
    strat_dd = (strat_cum / strat_cum.cummax() - 1).min()
    
    cash_days = hawk.sum()
    print(f"\n  Sell when spread {thresh_name}  (cash {cash_days}d / {cash_days/len(df)*100:.1f}%)")
    print(f"    Buy & Hold:  CAGR={bh_cagr*100:+.1f}%, MDD={bh_dd*100:.1f}%")
    print(f"    Hawk Strat:  CAGR={strat_cagr*100:+.1f}%, MDD={strat_dd*100:.1f}%")
    print(f"    Diff:        CAGR {(strat_cagr-bh_cagr)*100:+.1f}pp, MDD {(strat_dd-bh_dd)*100:+.1f}pp")

# Z-score based strategy
print("\n  --- Z-Score based (252d window, Z > 1.5) ---")
spread_z = df[f'spread_z_252']
hawk_z = spread_z > 1.5
strat_ret = df['QQQ_ret'].copy()
strat_ret[hawk_z] = 0

bh_cum = (1 + df['QQQ_ret']).cumprod()
strat_cum = (1 + strat_ret).cumprod()

years = (df.index[-1] - df.index[0]).days / 365.25
bh_cagr = bh_cum.iloc[-1] ** (1/years) - 1
strat_cagr = strat_cum.iloc[-1] ** (1/years) - 1
bh_dd = (bh_cum / bh_cum.cummax() - 1).min()
strat_dd = (strat_cum / strat_cum.cummax() - 1).min()
cash_days = hawk_z.sum()

print(f"    Cash {cash_days}d / {cash_days/len(df)*100:.1f}%")
print(f"    Buy & Hold:  CAGR={bh_cagr*100:+.1f}%, MDD={bh_dd*100:.1f}%")
print(f"    Z>1.5 Strat: CAGR={strat_cagr*100:+.1f}%, MDD={strat_dd*100:.1f}%")
print(f"    Diff:        CAGR {(strat_cagr-bh_cagr)*100:+.1f}pp, MDD {(strat_dd-bh_dd)*100:+.1f}pp")

# ============================================================================
# PART 5: 跟 SEP EXIT 的重叠度
# ============================================================================
print("\n")
print("=" * 80)
print("PART 5: 3M-FF 加息信号 vs SEP EXIT 重叠度")
print("=" * 80)

from strategy_engine import parse_sep_pdfs, build_sep_signals

sep_raw = parse_sep_pdfs(os.path.join(project_root, 'fomc_sep'))
sep_signals = build_sep_signals(sep_raw)
exits = [s for s in sep_signals if s['signal'] == 'EXIT']
enters = [s for s in sep_signals if s['signal'] == 'ENTER']

print(f"\nSEP EXIT events: {len(exits)}")
for ex in exits:
    exit_date = pd.Timestamp(ex['date'])
    # Check 3M-FF spread at and around EXIT date
    nearby = df.loc[exit_date - pd.DateOffset(days=5):exit_date + pd.DateOffset(days=5)]
    if len(nearby) == 0:
        print(f"  {ex['date']}: no data")
        continue
    row = nearby.iloc[len(nearby)//2]
    spread = row['spread']
    
    # Was spread hawkish in the month before?
    prior_month = df.loc[exit_date - pd.DateOffset(days=30):exit_date]
    hawk_days = (prior_month['spread'] > 0.10).sum() if len(prior_month) > 0 else 0
    avg_spread = prior_month['spread'].mean() if len(prior_month) > 0 else 0
    
    flag = "✅ ALIGNED" if spread > 0.05 else "❌ NOT aligned"
    print(f"  SEP EXIT {ex['date']}: spread={spread:+.3f}  "
          f"prior 30d avg={avg_spread:+.3f}  hawk days={hawk_days}  {flag}")

print("\n")
print("=" * 80)
print("CONCLUSION")
print("=" * 80)
