import re

with open('tools/build_dashboard.py', 'r') as f:
    text = f.read()

# 1. Replace sw() with sw_weekly and sw_daily
sw_code = """def sw_weekly(series):
    d = series.resample('W').last().dropna()
    return list(zip([x.strftime('%Y-%m-%d') for x in d.index], [round(float(v), 4) for v in d.values]))

def sw_daily(series):
    d = series.dropna()
    return list(zip([x.strftime('%Y-%m-%d') for x in d.index], [round(float(v), 4) for v in d.values]))
"""
text = re.sub(r'def sw\(series, daily_recent_days=504\):.*?return list\(zip\(\[x\.strftime\([^\]]+\]\)\)', sw_code, text, flags=re.DOTALL)

# 2. Update data_json
old_json = """    'eq_bh': sw(bh_eq),
    'eq_base': sw(es_base),
    'eq_opt': sw(es_opt),
    'z_score': sw(z_series),
    'vol_z': sw(vol_z.dropna()),"""
new_json = """    'eq_bh_w': sw_weekly(bh_eq), 'eq_bh_d': sw_daily(bh_eq),
    'eq_base_w': sw_weekly(es_base), 'eq_base_d': sw_daily(es_base),
    'eq_opt_w': sw_weekly(es_opt), 'eq_opt_d': sw_daily(es_opt),
    'z_score_w': sw_weekly(z_series), 'z_score_d': sw_daily(z_series),
    'vol_z_w': sw_weekly(vol_z.dropna()), 'vol_z_d': sw_daily(vol_z.dropna()),"""
text = text.replace(old_json, new_json)

# 3. Add UI buttons
header_html = """<div class="header" style="display:flex; justify-content:space-between; align-items:center;">
  <div>TQQQ Risk & Macro Dashboard</div>
  <div style="background:#FFF; padding:4px; border-radius:6px; box-shadow:0 1px 2px rgba(0,0,0,0.05); display:flex; gap:4px;">
    <button id="btn-daily" style="padding:4px 12px; border:none; background:#0055FF; color:#FFF; border-radius:4px; cursor:pointer; font-size:12px; font-weight:500;">Daily</button>
    <button id="btn-weekly" style="padding:4px 12px; border:none; background:transparent; color:#6B7280; border-radius:4px; cursor:pointer; font-size:12px; font-weight:500;">Weekly</button>
  </div>
</div>"""
text = text.replace('<div class="header">TQQQ Risk & Macro Dashboard</div>', header_html)

# 4. Update Javascript Plotly logic
js_old = """const eqOpt = unpack(D.eq_opt);
const eqBase = unpack(D.eq_base);
const eqBh = unpack(D.eq_bh);
const levData = unpack(D.lev_opt);

Plotly.newPlot('chart_equity', [
  { ...eqBh, name:'TQQQ Buy & Hold', type:'scatter', mode:'lines', line:{ color:'#EBEBEB', width:1.5 } },
  { ...eqBase, name:'Base TQQQ+SEP', type:'scatter', mode:'lines', line:{ color:'#A6B0C3', width:1.5 } },
  { ...eqOpt, name:'Protected (Current)', type:'scatter', mode:'lines', line:{ color:'#0055FF', width:2 } },
  { ...levData, name:'Leverage', type:'scatter', mode:'lines', fill:'tozeroy', fillcolor:'rgba(0, 85, 255, 0.05)', line:{ color:'#0055FF', width:1, shape:'hv', dash:'dot' }, yaxis:'y2' },
], { ...plotLayout, 
  yaxis:{ ...plotLayout.yaxis, type:'log' },
  yaxis2:{ overlaying:'y', side:'right', showgrid:false, range:[0, 3.5], tickvals:[0,1,2,3], tickfont:{color:'#A6B0C3'} },
  legend: { orientation: 'h', y: 1.05 }
}, cfg);

const zData = unpack(D.z_score);
Plotly.newPlot('chart_z', [
  { ...zData, name:'-(HYG/IEF) Z-Score', type:'scatter', mode:'lines', fill:'tozeroy', fillcolor:'rgba(255, 51, 58, 0.05)', line:{ color:'#FF333A', width:1.5 } }
], { ...plotLayout, margin:{ l:40, r:20, t:20, b:40 },
  shapes:[
    { type:'line', xref:'paper', x0:0, x1:1, y0:1.2, y1:1.2, line:{ color:'#FF333A', width:1.5, dash:'dash' } },
    { type:'line', xref:'paper', x0:0, x1:1, y0:0.2, y1:0.2, line:{ color:'#00C805', width:1.5, dash:'dash' } }
  ],
  yaxis:{ ...plotLayout.yaxis, title:'Stress Level' }
}, cfg);

const volZData = unpack(D.vol_z);
Plotly.newPlot('chart_vol', [
  { ...volZData, name:'Vol Z-Score', type:'scatter', mode:'lines', fill:'tozeroy', fillcolor:'rgba(0, 85, 255, 0.05)', line:{ color:'#0055FF', width:1.5 } }
], { ...plotLayout, margin:{ l:40, r:20, t:20, b:40 },
  shapes:[
    { type:'line', xref:'paper', x0:0, x1:1, y0:1.0, y1:1.0, line:{ color:'#FF333A', width:1.5, dash:'dash' } },
    { type:'line', xref:'paper', x0:0, x1:1, y0:-0.5, y1:-0.5, line:{ color:'#00C805', width:1.5, dash:'dash' } }
  ],
  yaxis:{ ...plotLayout.yaxis, title:'Vol Z-Score' }
}, cfg);"""

js_new = """let currentMode = 'daily';
const levData = unpack(D.lev_opt);

function renderCharts() {
  const eqOpt = unpack(D['eq_opt_' + (currentMode==='daily'?'d':'w')]);
  const eqBase = unpack(D['eq_base_' + (currentMode==='daily'?'d':'w')]);
  const eqBh = unpack(D['eq_bh_' + (currentMode==='daily'?'d':'w')]);
  
  Plotly.react('chart_equity', [
    { ...eqBh, name:'TQQQ Buy & Hold', type:'scatter', mode:'lines', line:{ color:'#EBEBEB', width:1.5 } },
    { ...eqBase, name:'Base TQQQ+SEP', type:'scatter', mode:'lines', line:{ color:'#A6B0C3', width:1.5 } },
    { ...eqOpt, name:'Protected (Current)', type:'scatter', mode:'lines', line:{ color:'#0055FF', width:2 } },
    { ...levData, name:'Leverage', type:'scatter', mode:'lines', fill:'tozeroy', fillcolor:'rgba(0, 85, 255, 0.05)', line:{ color:'#0055FF', width:1, shape:'hv', dash:'dot' }, yaxis:'y2' },
  ], { ...plotLayout, 
    yaxis:{ ...plotLayout.yaxis, type:'log' },
    yaxis2:{ overlaying:'y', side:'right', showgrid:false, range:[0, 3.5], tickvals:[0,1,2,3], tickfont:{color:'#A6B0C3'} },
    legend: { orientation: 'h', y: 1.05 }
  }, cfg);

  const zData = unpack(D['z_score_' + (currentMode==='daily'?'d':'w')]);
  Plotly.react('chart_z', [
    { ...zData, name:'-(HYG/IEF) Z-Score', type:'scatter', mode:'lines', fill:'tozeroy', fillcolor:'rgba(255, 51, 58, 0.05)', line:{ color:'#FF333A', width:1.5 } }
  ], { ...plotLayout, margin:{ l:40, r:20, t:20, b:40 },
    shapes:[
      { type:'line', xref:'paper', x0:0, x1:1, y0:1.2, y1:1.2, line:{ color:'#FF333A', width:1.5, dash:'dash' } },
      { type:'line', xref:'paper', x0:0, x1:1, y0:0.2, y1:0.2, line:{ color:'#00C805', width:1.5, dash:'dash' } }
    ],
    yaxis:{ ...plotLayout.yaxis, title:'Stress Level' }
  }, cfg);

  const volZData = unpack(D['vol_z_' + (currentMode==='daily'?'d':'w')]);
  Plotly.react('chart_vol', [
    { ...volZData, name:'Vol Z-Score', type:'scatter', mode:'lines', fill:'tozeroy', fillcolor:'rgba(0, 85, 255, 0.05)', line:{ color:'#0055FF', width:1.5 } }
  ], { ...plotLayout, margin:{ l:40, r:20, t:20, b:40 },
    shapes:[
      { type:'line', xref:'paper', x0:0, x1:1, y0:1.0, y1:1.0, line:{ color:'#FF333A', width:1.5, dash:'dash' } },
      { type:'line', xref:'paper', x0:0, x1:1, y0:-0.5, y1:-0.5, line:{ color:'#00C805', width:1.5, dash:'dash' } }
    ],
    yaxis:{ ...plotLayout.yaxis, title:'Vol Z-Score' }
  }, cfg);
}

document.getElementById('btn-daily').addEventListener('click', () => {
  currentMode = 'daily';
  document.getElementById('btn-daily').style.background = '#0055FF';
  document.getElementById('btn-daily').style.color = '#FFF';
  document.getElementById('btn-weekly').style.background = 'transparent';
  document.getElementById('btn-weekly').style.color = '#6B7280';
  renderCharts();
});

document.getElementById('btn-weekly').addEventListener('click', () => {
  currentMode = 'weekly';
  document.getElementById('btn-weekly').style.background = '#0055FF';
  document.getElementById('btn-weekly').style.color = '#FFF';
  document.getElementById('btn-daily').style.background = 'transparent';
  document.getElementById('btn-daily').style.color = '#6B7280';
  renderCharts();
});

renderCharts();"""
text = text.replace(js_old, js_new)

with open('tools/build_dashboard.py', 'w') as f:
    f.write(text)

