/* ============================================
   Tiny Monitor — Main Application
   ============================================ */

const App = (() => {
  let ws = null;
  let thresholds = {};
  let claudeDataReceived = false;
  let claudeDisconnectTimer = null;
  const CDP_TIMEOUT_MS = 30000;

  function init() {
    Settings.init();
    loadThresholds();
    connectWebSocket();
    fetchInitialData();
    startCdpTimeout();
  }

  function loadThresholds() {
    thresholds = Settings.getThresholds();
  }

  function onConfigSaved(config) {
    if (config && config.thresholds) {
      thresholds = {};
      for (const t of config.thresholds) {
        thresholds[t.metric] = { warning: t.warning, critical: t.critical };
      }
    }
  }

  // --- WebSocket ---

  function connectWebSocket() {
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const url = `${proto}//${location.host}/ws/live`;
    ws = new MonitorWebSocket(url);

    ws.on('open', () => updateConnectionStatus('connected'));
    ws.on('close', () => updateConnectionStatus('reconnecting'));
    ws.on('system_metrics', handleSystemMetrics);
    ws.on('claude_web', handleClaudeWeb);

    ws.connect();
  }

  function updateConnectionStatus(state) {
    const el = document.getElementById('connectionStatus');
    el.className = 'connection-status';
    const textEl = el.querySelector('.connection-status__text');

    if (state === 'connected') {
      el.classList.add('connection-status--connected');
      textEl.textContent = 'Live';
    } else if (state === 'reconnecting') {
      el.classList.add('connection-status--reconnecting');
      textEl.textContent = 'Reconnecting...';
    } else {
      textEl.textContent = 'Disconnected';
    }
  }

  // --- Fetch initial data via REST ---

  async function fetchInitialData() {
    try {
      const [metricsRes, configRes, cwRes] = await Promise.allSettled([
        fetch('/api/metrics'),
        fetch('/api/config'),
        fetch('/api/claude-web-usage'),
      ]);

      if (metricsRes.status === 'fulfilled' && metricsRes.value.ok) {
        const data = await metricsRes.value.json();
        handleSystemMetrics(data);
      }

      if (configRes.status === 'fulfilled' && configRes.value.ok) {
        const config = await configRes.value.json();
        if (config.thresholds) {
          for (const t of config.thresholds) {
            thresholds[t.metric] = { warning: t.warning, critical: t.critical };
          }
        }
      }

      if (cwRes.status === 'fulfilled' && cwRes.value.ok) {
        const data = await cwRes.value.json();
        handleClaudeWeb(data.data);
      }
    } catch (e) {
      // Server not running yet
    }
  }

  // --- System Metrics Handler ---

  function updateSysBar(barId, valId, cardId, pct, level) {
    const bar = document.getElementById(barId);
    const val = document.getElementById(valId);
    const card = document.getElementById(cardId);
    if (bar) {
      bar.style.width = Math.min(pct, 100) + '%';
      bar.className = 'sys-bar__fill';
      if (level === 'warning') bar.classList.add('sys-bar__fill--warning');
      if (level === 'critical') bar.classList.add('sys-bar__fill--critical');
    }
    if (val) val.textContent = Math.round(pct) + '%';
    if (card) {
      card.className = card.className.replace(/\s*sys-bar--(warning|critical)/g, '');
      if (level === 'warning') card.classList.add('sys-bar--warning');
      if (level === 'critical') card.classList.add('sys-bar--critical');
    }
  }

  function handleSystemMetrics(data) {
    if (!data) return;

    const t = thresholds;

    // CPU
    if (data.cpu) {
      const val = data.cpu.usage_percent;
      const th = t.cpu_percent || { warning: 80, critical: 95 };
      const level = Charts.getLevel(val, th.warning, th.critical);
      updateSysBar('barCpu', 'valCpu', 'cardCpu', val, level);
    }

    // Memory
    if (data.memory) {
      const val = data.memory.usage_percent;
      const th = t.memory_percent || { warning: 80, critical: 95 };
      const level = Charts.getLevel(val, th.warning, th.critical);
      updateSysBar('barMemory', 'valMemory', 'cardMemory', val, level);

      const detail = document.getElementById('memDetail');
      if (detail) {
        detail.textContent = `${data.memory.used_gb.toFixed(1)} / ${data.memory.total_gb.toFixed(1)} GB`;
      }
    }

    // Disk
    if (data.disk) {
      const val = data.disk.usage_percent;
      const th = t.disk_percent || { warning: 85, critical: 95 };
      const level = Charts.getLevel(val, th.warning, th.critical);
      updateSysBar('barDisk', 'valDisk', 'cardDisk', val, level);

      const detail = document.getElementById('diskDetail');
      if (detail) {
        detail.textContent = `${data.disk.used_gb.toFixed(0)} / ${data.disk.total_gb.toFixed(0)} GB`;
      }
    }

    // GPU (optional, show bar if present)
    if (data.gpu) {
      const gpuBar = document.getElementById('cardGpu');
      if (gpuBar) gpuBar.style.display = '';

      const val = data.gpu.usage_percent;
      const level = Charts.getLevel(val, 80, 95);
      updateSysBar('barGpu', 'valGpu', 'cardGpu', val, level);

      const detail = document.getElementById('gpuDetail');
      if (detail) {
        detail.textContent = `${(data.gpu.memory_used_mb / 1024).toFixed(1)} / ${(data.gpu.memory_total_mb / 1024).toFixed(1)} GB`;
      }
    }

    // Network
    if (data.network) {
      document.getElementById('netSent').textContent = Charts.formatBytes(data.network.bytes_sent_per_sec);
      document.getElementById('netRecv').textContent = Charts.formatBytes(data.network.bytes_recv_per_sec);
    }
  }

  // --- CDP Timeout ---

  function startCdpTimeout() {
    claudeDisconnectTimer = setTimeout(() => {
      if (!claudeDataReceived) {
        const disconnected = document.getElementById('claudeWebDisconnected');
        const meters = document.getElementById('claudeWebMeters');
        disconnected.style.display = '';
        meters.style.display = 'none';
      }
    }, CDP_TIMEOUT_MS);
  }

  // --- Claude Web Usage Handler ---

  function handleClaudeWeb(data) {
    const disconnected = document.getElementById('claudeWebDisconnected');
    const meters = document.getElementById('claudeWebMeters');

    if (!data) return;

    claudeDataReceived = true;
    if (claudeDisconnectTimer) {
      clearTimeout(claudeDisconnectTimer);
      claudeDisconnectTimer = null;
    }

    disconnected.style.display = 'none';
    meters.style.display = '';

    // Plan name in title
    const planEl = document.getElementById('claudeWebPlan');
    const planMap = {'맥스 플랜': 'MAX PLAN 5X', '프로 플랜': 'PRO PLAN', '팀 플랜': 'TEAM PLAN', '무료 플랜': 'FREE PLAN'};
    const planName = planMap[data.plan] || data.plan;
    planEl.textContent = planName ? `(${planName})` : '';

    // Build sys-bar style meters
    meters.innerHTML = '';

    const items = [
      { label: 'Claude Session', pct: data.session?.used_percent, reset: data.session?.reset_text },
      { label: 'Claude Weekly', pct: data.weekly_all?.used_percent, reset: data.weekly_all?.reset_text },
      { label: 'Claude Sonnet', pct: data.weekly_sonnet?.used_percent, reset: data.weekly_sonnet?.reset_text },
    ];

    for (const item of items) {
      if (item.pct == null) continue;
      const level = Charts.getLevel(item.pct, 60, 85);
      const fillClass = level !== 'normal' ? `sys-bar__fill--${level}` : '';
      const barClass = level !== 'normal' ? `sys-bar--${level}` : '';

      const row = document.createElement('div');
      row.className = `sys-bar ${barClass}`;
      row.innerHTML = `
        <span class="sys-bar__label">${escapeHtml(item.label)}</span>
        <div class="sys-bar__track"><div class="sys-bar__fill ${fillClass}" style="width:${Math.min(item.pct, 100)}%"></div></div>
        <span class="sys-bar__value">${Math.round(item.pct)}%</span>
        ${item.reset ? `<span class="sys-bar__detail">${escapeHtml(item.reset)}</span>` : ''}
      `;
      meters.appendChild(row);
    }
  }

  function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }

  return { init, onConfigSaved };
})();

document.addEventListener('DOMContentLoaded', App.init);
