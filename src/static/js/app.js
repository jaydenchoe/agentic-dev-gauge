/* ============================================
   Tiny Monitor — Main Application
   ============================================ */

const App = (() => {
  let ws = null;
  let thresholds = {};
  let claudeDataReceived = false;
  let claudeDisconnectTimer = null;
  let copilotDataReceived = false;
  let copilotDisconnectTimer = null;
  const CDP_TIMEOUT_MS = 30000;

  function init() {
    Settings.init();
    loadThresholds();
    connectWebSocket();
    fetchInitialData();
    startCdpTimeout();
    startCopilotCdpTimeout();
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
    ws.on('usage_update', handleUsageUpdate);

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
      const [metricsRes, configRes, cwRes, usageRes, copilotRes] = await Promise.allSettled([
        fetch('/api/metrics'),
        fetch('/api/config'),
        fetch('/api/claude-web-usage'),
        fetch('/api/usage'),
        fetch('/api/copilot-web-usage'),
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

      if (usageRes.status === 'fulfilled' && usageRes.value.ok) {
        const data = await usageRes.value.json();
        handleUsageUpdate(data);
      }

      if (copilotRes.status === 'fulfilled' && copilotRes.value.ok) {
        const data = await copilotRes.value.json();
        handleCopilotWeb(data.data);
      }
    } catch (e) {
      // Server not running yet
    }
  }

  // --- Bar Update ---

  function updateBar(fillId, valId, cardId, pct, level) {
    const fill = document.getElementById(fillId);
    const val = document.getElementById(valId);
    const card = document.getElementById(cardId);

    if (fill) {
      fill.style.width = Math.min(pct, 100) + '%';
      fill.className = 'bar__fill';
      if (level === 'warning') fill.classList.add('bar__fill--warning');
      if (level === 'critical') fill.classList.add('bar__fill--critical');
    }
    if (val) {
      val.innerHTML = `${Math.round(pct)}<span class="bar__unit">%</span>`;
      val.className = 'bar__value';
      if (level === 'warning') val.classList.add('bar__value--warning');
      if (level === 'critical') val.classList.add('bar__value--critical');
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
      updateBar('fillCpu', 'valCpu', 'cardCpu', val, level);
    }

    // Memory
    if (data.memory) {
      const val = data.memory.usage_percent;
      const th = t.memory_percent || { warning: 80, critical: 95 };
      const level = Charts.getLevel(val, th.warning, th.critical);
      updateBar('fillMemory', 'valMemory', 'cardMemory', val, level);

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
      updateBar('fillDisk', 'valDisk', 'cardDisk', val, level);

      const detail = document.getElementById('diskDetail');
      if (detail) {
        detail.textContent = `${data.disk.used_gb.toFixed(0)} / ${data.disk.total_gb.toFixed(0)} GB`;
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

    // Update Claude bars
    const items = [
      { fill: 'fillClaudeSession', val: 'valClaudeSession', card: 'cardClaudeSession', detail: 'detailClaudeSession', pct: data.session?.used_percent, reset: data.session?.reset_text },
      { fill: 'fillClaudeWeekly', val: 'valClaudeWeekly', card: 'cardClaudeWeekly', detail: 'detailClaudeWeekly', pct: data.weekly_all?.used_percent, reset: data.weekly_all?.reset_text },
      { fill: 'fillClaudeSonnet', val: 'valClaudeSonnet', card: 'cardClaudeSonnet', detail: 'detailClaudeSonnet', pct: data.weekly_sonnet?.used_percent, reset: data.weekly_sonnet?.reset_text },
    ];

    for (const item of items) {
      if (item.pct == null) continue;
      const level = Charts.getLevel(item.pct, 80, 90);
      updateBar(item.fill, item.val, item.card, item.pct, level);

      const detailEl = document.getElementById(item.detail);
      if (detailEl && item.reset) {
        detailEl.textContent = item.reset;
      }
    }

    // Extra usage
    const extraEl = document.getElementById('valClaudeExtra');
    if (extraEl && data.extra_usage) {
      const used = data.extra_usage.used_usd;
      const limit = data.extra_usage.limit_usd;
      if (used != null && limit != null) {
        extraEl.textContent = `$${used} / $${limit}`;
        extraEl.classList.remove('bar__value--muted');
      }
    }
  }

  // --- Copilot CDP Timeout ---

  function startCopilotCdpTimeout() {
    copilotDisconnectTimer = setTimeout(() => {
      if (!copilotDataReceived) {
        const disconnected = document.getElementById('copilotWebDisconnected');
        if (disconnected) disconnected.style.display = '';
      }
    }, CDP_TIMEOUT_MS);
  }

  // --- Copilot Web Usage Handler ---

  function handleCopilotWeb(data) {
    if (!data) return;

    copilotDataReceived = true;
    if (copilotDisconnectTimer) {
      clearTimeout(copilotDisconnectTimer);
      copilotDisconnectTimer = null;
    }

    const disconnected = document.getElementById('copilotWebDisconnected');
    if (disconnected) disconnected.style.display = 'none';

    // Plan name
    const planEl = document.getElementById('copilotPlan');
    if (planEl && data.plan) {
      planEl.textContent = data.plan.toUpperCase();
    }

    // Premium requests bar
    if (data.premium_used_percent != null) {
      const pct = data.premium_used_percent;
      const level = Charts.getLevel(pct, 80, 90);
      updateBar('fillCopilotPremium', 'valCopilotPremium', 'cardCopilotPremium', pct, level);

      const detailEl = document.getElementById('detailCopilotPremium');
      if (detailEl && data.reset_text) {
        detailEl.textContent = data.reset_text;
      }
    }
  }

  // --- Usage Update Handler (WebSocket "usage_update" channel) ---

  function handleUsageUpdate(data) {
    if (!data) return;

    // Forward nested claude_web data to the existing handler
    if (data.claude_web) {
      handleClaudeWeb(data.claude_web);
    }

    // Forward nested copilot_web data
    if (data.copilot_web) {
      handleCopilotWeb(data.copilot_web);
    }

    // Process per-provider token usages
    const usages = data.usages || [];
    for (const usage of usages) {
      if (usage.provider === 'zhipuai') {
        handleZhipuaiUsage(usage);
      }
    }
  }

  // --- ZhipuAI Usage Handler ---

  let zhipuaiPlanSet = false;

  function handleZhipuaiUsage(usage) {
    if (!usage) return;

    const model = usage.model || '';
    const pct = usage.quota_percentage != null ? usage.quota_percentage : null;

    // Set plan badge once from model string (e.g. "time-limit (max)")
    if (!zhipuaiPlanSet) {
      const planEl = document.getElementById('zhipuaiPlan');
      if (planEl) {
        const m = model.match(/\((\w+)\)/);
        if (m) {
          planEl.textContent = m[1].toUpperCase();
          zhipuaiPlanSet = true;
        }
      }
    }

    if (model.startsWith('time-limit')) {
      if (pct != null) {
        const level = Charts.getLevel(pct, 80, 90);
        updateBar('fillZhipuaiTime', 'valZhipuaiTime', 'cardZhipuaiTime', pct, level);
      }
      const detailEl = document.getElementById('detailZhipuaiTime');
      if (detailEl) {
        const limit = usage.quota_limit;
        const used = usage.total_tokens || 0;
        if (limit) {
          detailEl.textContent = `${used.toLocaleString()} / ${limit.toLocaleString()}`;
        }
        if (usage.reset_text) {
          detailEl.textContent = (detailEl.textContent ? detailEl.textContent + ' · ' : '') + usage.reset_text;
        }
      }
    } else if (model.startsWith('tokens-limit')) {
      if (pct != null) {
        const level = Charts.getLevel(pct, 80, 90);
        updateBar('fillZhipuaiTokens', 'valZhipuaiTokens', 'cardZhipuaiTokens', pct, level);
      }
      const detailEl = document.getElementById('detailZhipuaiTokens');
      if (detailEl && usage.reset_text) {
        detailEl.textContent = usage.reset_text;
      }
    }
  }

  return { init, onConfigSaved };
})();

document.addEventListener('DOMContentLoaded', App.init);
