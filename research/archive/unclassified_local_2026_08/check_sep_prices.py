#!/usr/bin/env python3
import sys; sys.path.insert(0,'tools')
import strategy_engine as se
import pandas as pd
import yfinance as yf

tqqq = yf.download('TQQQ', start='2012-01-01', progress=False, auto_adjust=False)
tqqq_cl = tqqq['Close'] if 'Close' in tqqq.columns else tqqq['Adj Close']
if isinstance(tqqq_cl, pd.DataFrame): tqqq_cl = tqqq_cl.iloc[:,0]

import os
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sep_raw = se.parse_sep_pdfs(os.path.join(PROJECT_DIR, 'fomc_sep'))
sep_signals = se.build_sep_signals(sep_raw)

events = []
for s in sep_signals:
    if s['signal']:
        dt = pd.Timestamp(s['date'])
        after = tqqq_cl.loc[tqqq_cl.index >= dt]
        if len(after) > 0:
            events.append({'date': s['date'], 'signal': s['signal'], 'price': float(after.iloc[0])})

hdr = f"  {'Period':<20} {'From':>12} {'To':>12} {'TQQQ From':>10} {'TQQQ To':>9} {'Move':>7} {'MDD':>7}  Verdict"
print(hdr)
print("  " + "─"*100)

for i in range(len(events)-1):
    e1, e2 = events[i], events[i+1]
    dt1, dt2 = pd.Timestamp(e1['date']), pd.Timestamp(e2['date'])
    p1, p2 = e1['price'], e2['price']
    move = (p2/p1 - 1) * 100
    days = (dt2 - dt1).days

    period_prices = tqqq_cl.loc[(tqqq_cl.index >= dt1) & (tqqq_cl.index <= dt2)]
    mdd = ((period_prices / period_prices.cummax()) - 1).min() * 100 if len(period_prices) > 0 else 0

    if e1['signal'] == 'EXIT':
        label = '🔴 OUT (cash)'
        verdict = '✅ Dodged' if move < -10 else ('⚠️ Missed upside' if move > 10 else '— Flat')
    else:
        label = '🟢 IN (3x)'
        verdict = '✅ Caught' if move > 10 else ('❌ Lost' if move < -10 else '— Flat')

    fp1 = f"${p1:.2f}"
    fp2 = f"${p2:.2f}"
    print(f"  {label:<20} {e1['date']:>12} {e2['date']:>12} {fp1:>10} {fp2:>9} {move:>+6.1f}% {mdd:>6.1f}%  {verdict} ({days}d)")

# Current ongoing period
last = events[-1]
dt_last = pd.Timestamp(last['date'])
cur_price = float(tqqq_cl.iloc[-1])
cur_date = tqqq_cl.index[-1].strftime('%Y-%m-%d')
period_prices = tqqq_cl.loc[tqqq_cl.index >= dt_last]
mdd = ((period_prices / period_prices.cummax()) - 1).min() * 100
move = (cur_price / last['price'] - 1) * 100
days = (pd.Timestamp(cur_date) - dt_last).days

if last['signal'] == 'EXIT':
    label = '🔴 OUT ← NOW'
else:
    label = '🟢 IN ← NOW'
fp1 = f"${last['price']:.2f}"
fp2 = f"${cur_price:.2f}"
print(f"  {label:<20} {last['date']:>12} {cur_date:>12} {fp1:>10} {fp2:>9} {move:>+6.1f}% {mdd:>6.1f}%  (ongoing, {days}d)")

# Summary
print()
out_moves = []
in_moves = []
for i in range(len(events)-1):
    e1, e2 = events[i], events[i+1]
    move = (e2['price']/e1['price'] - 1) * 100
    if e1['signal'] == 'EXIT':
        out_moves.append(move)
    else:
        in_moves.append(move)

print(f"  IN periods  ({len(in_moves)}x): avg = {sum(in_moves)/len(in_moves):+.1f}%")
print(f"  OUT periods ({len(out_moves)}x): avg = {sum(out_moves)/len(out_moves):+.1f}%")
print()
for i, m in enumerate(out_moves):
    status = '✅ dodged drop' if m < 0 else '❌ missed rally'
    print(f"    OUT {i+1}: TQQQ did {m:+.1f}% while in cash → {status}")
