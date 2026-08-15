# Failed Strategy Research — Do Not Repeat

Every idea here was tested and did not pass production criteria for the QQQ risk management strategy. They are documented here so future AI agents and researchers do not waste time re-testing dead ends.

| Idea | Hypothesis | Test | Result | Why rejected | Can reconsider if... |
|---|---|---|---|---|---|
| **EPS acceleration** | Accelerating earnings protect equities | Used macro EPS data to predict QQQ | CAGR -5% | 45-day data lag makes it useless for daily trading | We gain access to high-frequency, daily real-time EPS revisions |
| **EPS absolute growth** | Growth directly drives returns | EPS YoY vs QQQ returns | r = -0.09 | No short/medium-term predictive power | Focusing on 5-year investment horizons instead of tactical risk |
| **EPS mean reversion** | Extreme earnings revert, pulling prices | Tracked EPS cyclical peaks | CAGR -1.5% | Signal stays at the top too long during secular bull markets | Used only as a structural allocation filter, not tactical |
| **VIX Backwardation** | Inverted term structure signals max fear | Sold TQQQ when VIX < VIX3M | CAGR -0.7% | It signals bottom-fishing opportunities, not an escape hatch to avoid the drop | Building a counter-trend mean-reversion strategy |
| **HY OAS** | High Yield spreads are better than ETF proxies | Replaced HYG/IEF with FRED OAS | Data too short | Often coincident or lagging compared to liquid ETFs | Better historical daily data becomes available pre-2005 |
| **VIX + Momentum** | Trend-following the VIX works | VIX SMA crosses | T+1: -1.5% | Severe look-ahead bias in close-to-close implementation | Developing intraday real-time streaming VIX execution |
| **TQQQ Overnight** | Intraday holds all the risk | Buy close, sell open | -89.5% w/ TC | Transaction costs (TC) completely destroy any edge | Commission-free trading with zero slippage exists at scale |
| **TQQQ Overnight sell-if-profit** | Filter overnight by profitable setups | Buy close, sell open conditionally | +21.7% vs B&H +43.4% | 1% TC drag still exceeds the statistical edge | Managing billions where overnight gap risk is strictly prohibited |
| **Concentration as sell signal** | High top-5 weight means a fragile bubble | NDX concentration metric | High conc → UP | High concentration historically correlates with bullish momentum, not crashes | The market structure fundamentally shifts away from tech dominance |
| **NFCI / STLFSI stress** | Fed stress indices are the ultimate macro truth | Replaced Credit Z with NFCI | r=0.68 w/ Credit Z | Redundant; Credit Z updates instantly via ETFs, while NFCI has lag | Building a monthly macroeconomic rebalancing model |
| **Corporate profits** | Macro profits matter | FRED CP data | Only < -10% YoY | Quarterly reporting frequency means it severely lags price action | Combining with high-frequency proxy variables |
| **Earnings / SOXX override** | Semiconductors lead the Nasdaq | Used SOXX momentum as override | No edge | No significant differentiation from QQQ's own momentum | Semiconductor divergence reaches historically unprecedented levels |
| **Shiller CAPE for QQQ** | High valuation equals high risk | CAPE ratio | Monthly, S&P only | No free daily NDX CAPE data; S&P data is too broad and slow | A reliable daily NDX CAPE API is procured |
| **Price Stretch > 1.20** | Extreme overbought is a crash warning | Price / 200 SMA > 1.20 | 0 days in IS | The threshold was too high, triggering zero events in the in-sample period | Lowering the threshold and studying momentum exhaustion |
| **V3 Quiet Bleed** | Slow grinds down can be caught | Price Stretch 0.94-1.19 | Blind spot NOT fixed | It failed to protect during the exact "quiet bleed" drawdowns it was meant for | A fundamentally new mathematical definition of "bleed" is found |
