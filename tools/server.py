#!/usr/bin/env python3
"""
TQQQ Strategy Server
====================
Local web server that serves the dashboard and provides API for live updates.
"""
import os, sys, json, subprocess, threading, time, webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timedelta

# FOMC SEP meeting dates (quarterly)
FOMC_SEP_DATES = [
    '2026-03-18','2026-06-17','2026-09-16','2026-12-16',
    '2027-03-17','2027-06-16','2027-09-22','2027-12-15',
    '2028-03-15','2028-06-14','2028-09-20','2028-12-13',
]

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = 8808

# Track update state
update_state = {
    'is_updating': False,
    'last_update': None,
    'last_log': '',
}

class DashboardHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # Suppress default logging

    def do_GET(self):
        if self.path == '/' or self.path == '/index.html':
            self._serve_dashboard()
        elif self.path == '/api/status':
            self._serve_status()
        elif self.path == '/z_score_explanation.html':
            self._serve_file('z_score_explanation.html', 'text/html')
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path == '/api/update':
            self._trigger_update()
        else:
            self.send_error(404)

    def _serve_dashboard(self):
        html_path = os.path.join(PROJECT_DIR, 'tools', 'robustness_dashboard.html')
        if not os.path.exists(html_path):
            self.send_error(404, 'Dashboard not built yet. Click Update.')
            return
        
        with open(html_path, 'r') as f:
            html = f.read()
        
        # Inject the update toolbar into the dashboard
        toolbar = self._build_toolbar()
        html = html.replace('</body>', toolbar + '\n</body>')
        
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(html.encode('utf-8'))

    def _serve_status(self):
        # Read data freshness from market_data CSVs
        data_dir = os.path.join(PROJECT_DIR, 'market_data')
        freshness = {}
        for fn in ['yahoo_QQQ.csv', 'yahoo_TQQQ.csv', 'yahoo_HYG.csv', 'yahoo_IEF.csv']:
            path = os.path.join(data_dir, fn)
            if os.path.exists(path):
                mtime = os.path.getmtime(path)
                freshness[fn.replace('yahoo_','').replace('.csv','')] = {
                    'file_updated': datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M'),
                }
        
        # Count SEP files
        sep_dir = os.path.join(PROJECT_DIR, 'fomc_sep')
        sep_count = len([f for f in os.listdir(sep_dir) if f.endswith('.pdf')]) if os.path.isdir(sep_dir) else 0
        sep_latest = ''
        if os.path.isdir(sep_dir):
            pdfs = sorted([f for f in os.listdir(sep_dir) if f.endswith('.pdf')])
            if pdfs:
                sep_latest = pdfs[-1].replace('fomc_sep_','').replace('.pdf','')

        # Dashboard file age
        dash_path = os.path.join(PROJECT_DIR, 'tools', 'robustness_dashboard.html')
        dash_age = ''
        if os.path.exists(dash_path):
            mtime = os.path.getmtime(dash_path)
            dash_age = datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M')

        # Next FOMC SEP date
        today = datetime.now().strftime('%Y-%m-%d')
        next_fomc = None
        days_until = None
        for d in FOMC_SEP_DATES:
            if d > today:
                next_fomc = d
                days_until = (datetime.strptime(d, '%Y-%m-%d') - datetime.now()).days
                break

        # Check if a past FOMC SEP is missing
        missing_sep = None
        for d in FOMC_SEP_DATES:
            if d <= today and d > sep_latest:
                missing_sep = d
                break

        resp = {
            'is_updating': update_state['is_updating'],
            'last_update': update_state['last_update'],
            'last_log': update_state['last_log'],
            'data_freshness': freshness,
            'sep_count': sep_count,
            'sep_latest': sep_latest,
            'dashboard_generated': dash_age,
            'next_fomc': next_fomc,
            'days_until_fomc': days_until,
            'missing_sep': missing_sep,
        }
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(resp).encode())

    def _trigger_update(self):
        if update_state['is_updating']:
            self.send_response(429)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'error': 'Update already in progress'}).encode())
            return

        update_state['is_updating'] = True
        update_state['last_log'] = 'Starting update...'

        def run_update():
            try:
                script = os.path.join(PROJECT_DIR, 'tools', 'auto_update.py')
                result = subprocess.run(
                    [sys.executable, script],
                    capture_output=True, text=True, cwd=PROJECT_DIR, timeout=120
                )
                update_state['last_log'] = result.stdout + result.stderr
                update_state['last_update'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            except subprocess.TimeoutExpired:
                update_state['last_log'] = 'ERROR: Update timed out after 120s'
            except Exception as e:
                update_state['last_log'] = f'ERROR: {str(e)}'
            finally:
                update_state['is_updating'] = False

        t = threading.Thread(target=run_update, daemon=True)
        t.start()

        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps({'status': 'started'}).encode())

    def _serve_file(self, filename, content_type):
        path = os.path.join(PROJECT_DIR, filename)
        if not os.path.exists(path):
            self.send_error(404)
            return
        with open(path, 'rb') as f:
            data = f.read()
        self.send_response(200)
        self.send_header('Content-Type', content_type)
        self.end_headers()
        self.wfile.write(data)

    def _build_toolbar(self):
        return '''
<!-- Bottom Toolbar -->
<div id="update-toolbar" style="
  position:fixed; bottom:0; left:0; right:0; z-index:9999;
  background:#FFFFFF; border-top:1px solid #EBEBEB;
  padding:10px 24px; display:flex; align-items:center; justify-content:space-between;
  font-family:'Roboto',sans-serif; font-size:13px; color:#6B7280;
  box-shadow:0 -2px 8px rgba(0,0,0,0.06);
">
  <div style="display:flex; align-items:center; gap:16px;">
    <button id="btn-update" onclick="triggerUpdate()" style="
      background:#0055FF; color:white; border:none; border-radius:6px;
      padding:8px 20px; font-size:13px; font-weight:700; cursor:pointer;
      font-family:'Roboto',sans-serif; transition:all 0.2s;
    " onmouseover="this.style.background='#0044CC'" onmouseout="this.style.background='#0055FF'">
      🔄 Update
    </button>
    <div id="status-text" style="color:#6B7280; font-size:12px;">Loading...</div>
  </div>
  <div style="display:flex; align-items:center; gap:16px;">
    <div id="freshness-info" style="display:flex; gap:12px; font-size:11px; color:#A6B0C3;"></div>
    <!-- Bell -->
    <div style="position:relative;">
      <div id="bell-btn" onclick="toggleBell()" style="
        cursor:pointer; font-size:20px; position:relative; padding:4px 8px;
        border-radius:6px; transition:background 0.2s;
      " onmouseover="this.style.background='#F4F5F7'" onmouseout="this.style.background='transparent'">
        🔔
        <span id="bell-badge" style="
          display:none; position:absolute; top:0; right:2px;
          background:#FF333A; color:white; font-size:10px; font-weight:700;
          width:16px; height:16px; border-radius:50%;
          display:flex; align-items:center; justify-content:center;
        ">0</span>
      </div>
      <!-- Notification Dropdown -->
      <div id="bell-dropdown" style="
        display:none; position:absolute; bottom:40px; right:0;
        background:#FFFFFF; border:1px solid #EBEBEB; border-radius:10px;
        box-shadow:0 8px 30px rgba(0,0,0,0.12); width:340px;
        font-family:'Roboto',sans-serif; overflow:hidden;
      ">
        <div style="padding:14px 16px; border-bottom:1px solid #F0F0F0; font-weight:700; color:#111827; font-size:14px;">Notifications</div>
        <div id="bell-items" style="max-height:320px; overflow-y:auto;"></div>
      </div>
    </div>
  </div>
</div>
<div style="height:50px;"></div>

<!-- Update Modal -->
<div id="update-modal" style="
  display:none; position:fixed; top:0; left:0; right:0; bottom:0; z-index:10000;
  background:rgba(0,0,0,0.5); justify-content:center; align-items:center;
">
  <div style="
    background:white; border-radius:12px; padding:24px; width:600px; max-height:80vh;
    overflow-y:auto; box-shadow:0 20px 60px rgba(0,0,0,0.3);
    font-family:'Roboto',sans-serif;
  ">
    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:16px;">
      <h3 style="margin:0; color:#111827;">Update Log</h3>
      <button onclick="closeModal()" style="
        background:none; border:1px solid #EBEBEB; border-radius:6px;
        padding:6px 16px; cursor:pointer; font-size:13px; color:#6B7280;
      ">Close</button>
    </div>
    <pre id="update-log" style="
      background:#F4F5F7; padding:16px; border-radius:8px; font-size:12px;
      white-space:pre-wrap; word-wrap:break-word; color:#111827;
      max-height:400px; overflow-y:auto; line-height:1.6;
    "></pre>
    <div id="modal-status" style="margin-top:12px; font-size:13px; color:#6B7280;"></div>
  </div>
</div>

<script>
let pollInterval = null;
let bellOpen = false;

function toggleBell() {
  bellOpen = !bellOpen;
  document.getElementById('bell-dropdown').style.display = bellOpen ? 'block' : 'none';
}
document.addEventListener('click', function(e) {
  if (!e.target.closest('#bell-btn') && !e.target.closest('#bell-dropdown')) {
    bellOpen = false;
    document.getElementById('bell-dropdown').style.display = 'none';
  }
});

function triggerUpdate() {
  const btn = document.getElementById('btn-update');
  btn.disabled = true;
  btn.innerHTML = '⏳ Updating...';
  btn.style.background = '#A6B0C3';
  fetch('/api/update', { method: 'POST' })
    .then(r => r.json())
    .then(d => {
      document.getElementById('update-modal').style.display = 'flex';
      document.getElementById('update-log').textContent = 'Update started...\\n';
      document.getElementById('modal-status').textContent = 'Running...';
      pollInterval = setInterval(pollUpdate, 1500);
    })
    .catch(e => {
      btn.disabled = false; btn.innerHTML = '🔄 Update'; btn.style.background = '#0055FF';
      alert('Failed: ' + e.message);
    });
}

function pollUpdate() {
  fetch('/api/status').then(r => r.json()).then(d => {
    document.getElementById('update-log').textContent = d.last_log || 'Waiting...';
    if (!d.is_updating) {
      clearInterval(pollInterval);
      const btn = document.getElementById('btn-update');
      btn.disabled = false; btn.innerHTML = '🔄 Update'; btn.style.background = '#0055FF';
      document.getElementById('modal-status').innerHTML =
        '<span style="color:#00C805;font-weight:700">✅ Done!</span> ' +
        '<button onclick="location.reload()" style="background:#0055FF;color:white;border:none;border-radius:4px;padding:6px 16px;cursor:pointer;font-weight:700;margin-left:8px">Reload</button>';
    }
  });
}

function closeModal() { document.getElementById('update-modal').style.display = 'none'; }

function loadStatus() {
  fetch('/api/status').then(r => r.json()).then(d => {
    // Status text
    const stEl = document.getElementById('status-text');
    if (d.dashboard_generated) {
      stEl.innerHTML = 'Last build: <strong>' + d.dashboard_generated + '</strong>';
    }

    // Freshness
    const frEl = document.getElementById('freshness-info');
    let frHtml = '';
    if (d.sep_latest) frHtml += '<span>SEP: <strong>' + d.sep_latest + '</strong></span>';
    frEl.innerHTML = frHtml;

    // Build notifications
    let notes = [];
    let alertCount = 0;

    // 1. Next FOMC
    if (d.next_fomc) {
      const days = d.days_until_fomc;
      if (days <= 7) {
        notes.push({ icon: '🔴', text: 'FOMC SEP in <strong>' + days + ' days</strong> (' + d.next_fomc + ')', urgent: true });
        alertCount++;
      } else if (days <= 30) {
        notes.push({ icon: '🟡', text: 'Next FOMC SEP in <strong>' + days + ' days</strong> (' + d.next_fomc + ')', urgent: false });
      } else {
        notes.push({ icon: '📅', text: 'Next FOMC SEP: <strong>' + d.next_fomc + '</strong> (' + days + ' days)', urgent: false });
      }
    }

    // 2. Missing SEP PDF
    if (d.missing_sep) {
      notes.push({ icon: '🚨', text: 'Missing SEP PDF for <strong>' + d.missing_sep + '</strong> — Click Update!', urgent: true });
      alertCount++;
    }

    // 3. Stale data
    if (d.dashboard_generated) {
      const genDate = new Date(d.dashboard_generated.replace(' ', 'T'));
      const hoursDiff = (new Date() - genDate) / (1000*60*60);
      if (hoursDiff > 48) {
        notes.push({ icon: '⚠️', text: 'Data is <strong>' + Math.floor(hoursDiff/24) + ' days old</strong> — Update recommended', urgent: true });
        alertCount++;
      } else {
        notes.push({ icon: '✅', text: 'Market data is <strong>up to date</strong>', urgent: false });
      }
    }

    // 4. SEP data info
    notes.push({ icon: '📄', text: 'SEP database: <strong>' + d.sep_count + ' files</strong>, latest: ' + d.sep_latest, urgent: false });

    // Render bell badge
    const badge = document.getElementById('bell-badge');
    if (alertCount > 0) {
      badge.style.display = 'flex';
      badge.textContent = alertCount;
    } else {
      badge.style.display = 'none';
    }

    // Render notifications
    const itemsEl = document.getElementById('bell-items');
    itemsEl.innerHTML = notes.map(n =>
      '<div style="padding:12px 16px; border-bottom:1px solid #F0F0F0; font-size:13px; color:' + (n.urgent ? '#111827' : '#6B7280') + ';">' +
      '<span style="margin-right:8px;">' + n.icon + '</span>' + n.text + '</div>'
    ).join('');
  }).catch(() => {
    document.getElementById('status-text').textContent = 'Offline';
  });
}

loadStatus();
setInterval(loadStatus, 60000);
</script>
'''

def main():
    # Kill existing server on same port
    os.system(f'lsof -ti:{PORT} | xargs kill -9 2>/dev/null')
    time.sleep(0.3)

    server = HTTPServer(('127.0.0.1', PORT), DashboardHandler)
    url = f'http://localhost:{PORT}'
    
    print(f'╔══════════════════════════════════════════╗')
    print(f'║   TQQQ Strategy Dashboard Server         ║')
    print(f'║   Running at: {url:<25s} ║')
    print(f'║   Press Ctrl+C to stop                   ║')
    print(f'╚══════════════════════════════════════════╝')
    
    # Open browser after short delay
    def open_browser():
        time.sleep(1)
        webbrowser.open(url)
    threading.Thread(target=open_browser, daemon=True).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\n🛑 Server stopped.')
        server.server_close()

if __name__ == '__main__':
    main()
