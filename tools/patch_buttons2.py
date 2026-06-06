import re

with open('tools/build_dashboard.py', 'r') as f:
    text = f.read()

# 1. Remove global toggle
global_toggle = """<div class="menu" style="display:flex; align-items:center; gap:16px;">
    <div class="active">Overview</div>
    <div style="background:rgba(255,255,255,0.15); padding:3px; border-radius:6px; display:flex; gap:2px;">
      <button id="btn-daily" onclick="setMode('daily')" style="padding:4px 14px; border:none; background:#FFFFFF; color:#111827; border-radius:4px; cursor:pointer; font-size:12px; font-weight:600;">Daily</button>
      <button id="btn-weekly" onclick="setMode('weekly')" style="padding:4px 14px; border:none; background:transparent; color:rgba(255,255,255,0.7); border-radius:4px; cursor:pointer; font-size:12px; font-weight:500;">Weekly</button>
    </div>
  </div>"""
text = text.replace(global_toggle, '<div class="menu"><div class="active">Overview</div></div>')

# 2. Define button HTML helper
def btn_html(id_prefix):
    return f"""<div style="background:#F0F0F0; padding:2px; border-radius:6px; display:flex; gap:2px;">
      <button id="btn-{id_prefix}-d" onclick="setMode('{id_prefix}', 'daily')" style="padding:4px 12px; border:none; background:#FFFFFF; color:#111827; border-radius:4px; cursor:pointer; font-size:11px; font-weight:600; box-shadow:0 1px 2px rgba(0,0,0,0.05);">Daily</button>
      <button id="btn-{id_prefix}-w" onclick="setMode('{id_prefix}', 'weekly')" style="padding:4px 12px; border:none; background:transparent; color:#6B7280; border-radius:4px; cursor:pointer; font-size:11px; font-weight:500;">Weekly</button>
    </div>"""

# 3. Add to Equity panel
text = text.replace(
    '<div class="panel-header">\n        <div>Equity Growth & Target Leverage</div>\n        <div class="note">Log Scale • Since 2012</div>\n      </div>',
    f'<div class="panel-header" style="display:flex; justify-content:space-between; align-items:center;">\n        <div>Equity Growth & Target Leverage</div>\n        <div style="display:flex; align-items:center; gap:12px;">\n          {btn_html("eq")}\n          <div class="note" style="font-weight:400; font-size:12px;">Log Scale • Since 2012</div>\n        </div>\n      </div>'
)

# 4. Add to Z-Score panel
text = text.replace(
    '<div>-(HYG / IEF) Credit Stress Radar</div>\n        <div class="note" style="font-size:12px; font-weight:400; color:#A6B0C3;">Data: {source_dates[\'hyg\']}</div>',
    f'<div>-(HYG / IEF) Credit Stress Radar</div>\n        <div style="display:flex; align-items:center; gap:12px;">\n          {btn_html("z")}\n          <div class="note" style="font-size:12px; font-weight:400; color:#A6B0C3;">Data: {{source_dates["hyg"]}}</div>\n        </div>'
)

# 5. Add to Vol Z-Score panel
text = text.replace(
    '<div>Realized Volatility Z-Score Radar</div>\n        <div class="note" style="font-size:12px; font-weight:400; color:#A6B0C3;">Data: {source_dates[\'tqqq\']}</div>',
    f'<div>Realized Volatility Z-Score Radar</div>\n        <div style="display:flex; align-items:center; gap:12px;">\n          {btn_html("vol")}\n          <div class="note" style="font-size:12px; font-weight:400; color:#A6B0C3;">Data: {{source_dates["tqqq"]}}</div>\n        </div>'
)

# 6. Add rangeselector to layout
old_xaxis = "xaxis:{ gridcolor:'#F0F0F0', linecolor:'#EBEBEB', tickfont:{color:'#A6B0C3'}, hoverformat:'%Y-%m-%d' },"
new_xaxis = """xaxis:{ 
    gridcolor:'#F0F0F0', linecolor:'#EBEBEB', tickfont:{color:'#A6B0C3'}, hoverformat:'%Y-%m-%d',
    rangeselector: {
      buttons: [
        {count: 1, label: '1y', step: 'year', stepmode: 'backward'},
        {count: 2, label: '2y', step: 'year', stepmode: 'backward'},
        {count: 5, label: '5y', step: 'year', stepmode: 'backward'},
        {step: 'all', label: 'All'}
      ],
      font: {size: 11, color: '#6B7280'},
      bgcolor: '#F9FAFB',
      activecolor: '#EBEBEB',
      bordercolor: '#EBEBEB',
      borderwidth: 1
    }
  },"""
text = text.replace(old_xaxis, new_xaxis)

# 7. Rewrite JS
start_js = "function barColors(yArr) {"
end_js = "renderCharts();"

import re
text = re.sub(r'function barColors\(yArr\) \{.*?renderCharts\(\);', """function barColors(yArr) {
  return yArr.map((v, i) => i === 0 ? '#A6B0C3' : (v > yArr[i-1] ? '#FF333A' : '#00C805'));
}

const levData = unpack(D.lev_opt);
const modes = { eq: 'daily', z: 'daily', vol: 'daily' };

function renderEq() {
  const s = modes.eq === 'daily' ? '_d' : '_w';
  const eqOpt = unpack(D['eq_opt' + s]);
  const eqBase = unpack(D['eq_base' + s]);
  const eqBh = unpack(D['eq_bh' + s]);
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
}

function renderZ() {
  const s = modes.z === 'daily' ? '_d' : '_w';
  const zData = unpack(D['z_score' + s]);
  Plotly.react('chart_z', [
    { x: zData.x, y: zData.y, name:'-(HYG/IEF) Z-Score', type:'bar', marker:{ color: barColors(zData.y) } }
  ], { ...plotLayout, margin:{ l:40, r:20, t:20, b:40 },
    shapes:[
      { type:'line', xref:'paper', x0:0, x1:1, y0:1.2, y1:1.2, line:{ color:'#FF333A', width:1.5, dash:'dash' } },
      { type:'line', xref:'paper', x0:0, x1:1, y0:0.2, y1:0.2, line:{ color:'#00C805', width:1.5, dash:'dash' } }
    ],
    yaxis:{ ...plotLayout.yaxis, title:'Stress Level' },
    bargap: 0
  }, cfg);
}

function renderVol() {
  const s = modes.vol === 'daily' ? '_d' : '_w';
  const volZData = unpack(D['vol_z' + s]);
  Plotly.react('chart_vol', [
    { x: volZData.x, y: volZData.y, name:'Vol Z-Score', type:'bar', marker:{ color: barColors(volZData.y) } }
  ], { ...plotLayout, margin:{ l:40, r:20, t:20, b:40 },
    shapes:[
      { type:'line', xref:'paper', x0:0, x1:1, y0:1.0, y1:1.0, line:{ color:'#FF333A', width:1.5, dash:'dash' } },
      { type:'line', xref:'paper', x0:0, x1:1, y0:-0.5, y1:-0.5, line:{ color:'#00C805', width:1.5, dash:'dash' } }
    ],
    yaxis:{ ...plotLayout.yaxis, title:'Vol Z-Score' },
    bargap: 0
  }, cfg);
}

function setMode(chart, mode) {
  modes[chart] = mode;
  const bd = document.getElementById('btn-' + chart + '-d');
  const bw = document.getElementById('btn-' + chart + '-w');
  if (mode === 'daily') {
    bd.style.background = '#FFFFFF'; bd.style.color = '#111827'; bd.style.fontWeight = '600'; bd.style.boxShadow = '0 1px 2px rgba(0,0,0,0.05)';
    bw.style.background = 'transparent'; bw.style.color = '#6B7280'; bw.style.fontWeight = '500'; bw.style.boxShadow = 'none';
  } else {
    bw.style.background = '#FFFFFF'; bw.style.color = '#111827'; bw.style.fontWeight = '600'; bw.style.boxShadow = '0 1px 2px rgba(0,0,0,0.05)';
    bd.style.background = 'transparent'; bd.style.color = '#6B7280'; bd.style.fontWeight = '500'; bd.style.boxShadow = 'none';
  }
  if (chart === 'eq') renderEq();
  if (chart === 'z') renderZ();
  if (chart === 'vol') renderVol();
}

renderEq();
renderZ();
renderVol();""", text, flags=re.DOTALL)

with open('tools/build_dashboard.py', 'w') as f:
    f.write(text)

