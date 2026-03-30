/* ============================================
   Tiny Monitor — Main Application
   ============================================ */

const App = (() => {
  let ws = null;
  let thresholds = {};
  let claudeDataReceived = false;
  let claudeDisconnectTimer = null;
  const CDP_TIMEOUT_MS = 30000;
  const CIRCUMFERENCE = 314.16; // 2 * PI * 50

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

  // --- Gauge Update ---

  function updateGauge(fillId, valId, cardId, pct, level) {
    const fill = document.getElementById(fillId);
    const val = document.getElementById(valId);
    const card = document.getElementById(cardId);

    if (fill) {
      const offset = CIRCUMFERENCE * (1 - Math.min(pct, 100) / 100);
      fill.style.strokeDashoffset = offset;
      fill.className.baseVal = 'gauge__fill';
      if (level === 'warning') fill.classList.add('gauge__fill--warning');
      if (level === 'critical') fill.classList.add('gauge__fill--critical');
    }
    if (val) {
      val.innerHTML = `${Math.round(pct)}<span class="gauge__unit">%</span>`;
      val.className = 'gauge__value';
      if (level === 'warning') val.classList.add('gauge__value--warning');
      if (level === 'critical') val.classList.add('gauge__value--critical');
    }
    if (card) {
      card.className = card.className.replace(/\s*card--(warning|critical)/g, '');
      if (level === 'warning') card.classList.add('card--warning');
      if (level === 'critical') card.classList.add('card--critical');
    }
  }

  // --- System Metrics Handler ---

  function handleSystemMetrics(data) {
    if (!data) return;

    const t = thresholds;

    // CPU
    if (data.cpu) {
      const val = data.cpu.usage_percent;
      const th = t.cpu_percent || { warning: 80, critical: 95 };
      const level = Charts.getLevel(val, th.warning, th.critical);
      updateGauge('fillCpu', 'valCpu', 'cardCpu', val, level);
    }

    // Memory
    if (data.memory) {
      const val = data.memory.usage_percent;
      const th = t.memory_percent || { warning: 80, critical: 95 };
      const level = Charts.getLevel(val, th.warning, th.critical);
      updateGauge('fillMemory', 'valMemory', 'cardMemory', val, level);

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
      updateGauge('fillDisk', 'valDisk', 'cardDisk', val, level);

      const detail = document.getElementById('diskDetail');
      if (detail) {
        detail.textContent = `${data.disk.used_gb.toFixed(0)} / ${data.disk.total_gb.toFixed(0)} GB`;
      }
    }

    // GPU
    if (data.gpu) {
      const val = data.gpu.usage_percent;
      const level = Charts.getLevel(val, 80, 95);
      updateGauge('fillGpu', 'valGpu', 'cardGpu', val, level);

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
        if (disconnected) disconnected.style.display = '';
      }
    }, CDP_TIMEOUT_MS);
  }

  // --- Claude Web Usage Handler ---

  function handleClaudeWeb(data) {
    if (!data) return;

    claudeDataReceived = true;
    if (claudeDisconnectTimer) {
      clearTimeout(claudeDisconnectTimer);
      claudeDisconnectTimer = null;
    }

    const disconnected = document.getElementById('claudeWebDisconnected');
    if (disconnected) disconnected.style.display = 'none';

    // Plan name
    const planEl = document.getElementById('claudeWebPlan');
    if (planEl) {
      const planMap = {'맥스 플랜': 'MAX 5X', '프로 플랜': 'PRO', '팀 플랜': 'TEAM', '무료 플랜': 'FREE'};
      const planName = planMap[data.plan] || data.plan;
      planEl.textContent = planName || '';
    }

    // Update Claude gauges
    const items = [
      { fill: 'fillClaudeSession', val: 'valClaudeSession', card: 'cardClaudeSession', detail: 'detailClaudeSession', pct: data.session?.used_percent, reset: data.session?.reset_text },
      { fill: 'fillClaudeWeekly', val: 'valClaudeWeekly', card: 'cardClaudeWeekly', detail: 'detailClaudeWeekly', pct: data.weekly_all?.used_percent, reset: data.weekly_all?.reset_text },
      { fill: 'fillClaudeSonnet', val: 'valClaudeSonnet', card: 'cardClaudeSonnet', detail: 'detailClaudeSonnet', pct: data.weekly_sonnet?.used_percent, reset: data.weekly_sonnet?.reset_text },
    ];

    for (const item of items) {
      if (item.pct == null) continue;
      const level = Charts.getLevel(item.pct, 60, 85);
      updateGauge(item.fill, item.val, item.card, item.pct, level);

      const detailEl = document.getElementById(item.detail);
      if (detailEl && item.reset) {
        detailEl.textContent = item.reset;
      }
    }
  }

  return { init, onConfigSaved };
})();

document.addEventListener('DOMContentLoaded', App.init);
