/* ============================================
   Agentic Dev Gauge — Main Application
   ============================================ */

const App = (() => {
  let ws = null;
  let thresholds = {};
  let claudeDataReceived = false;
  let claudeDisconnectTimer = null;
  const codexUsageState = {};
  const CDP_TIMEOUT_MS = 30000;
  const DEFAULT_OLLAMA_BASE_URL = 'http://127.0.0.1:11434';
  const trendData = {};
  const TREND_MAX = 40;
  let startTime = Date.now();

  function init() {
    Settings.init();
    loadThresholds();
    connectWebSocket();
    fetchInitialData();
    startCdpTimeout();
    startClock();
  }

  function startClock() {
    function tick() {
      const t = new Date();
      const clockEl = document.getElementById('clock');
      if (clockEl) clockEl.textContent = t.toTimeString().slice(0, 8);

      const dateEl = document.getElementById('topbarDate');
      if (dateEl && !dateEl.textContent) {
        dateEl.textContent = ' · ' + t.toLocaleDateString('en-US', { day: 'numeric', month: 'short', year: 'numeric' }).toUpperCase();
      }

      const uptimeEl = document.getElementById('uptime');
      if (uptimeEl) {
        const s = Math.floor((Date.now() - startTime) / 1000);
        const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
        uptimeEl.textContent = [h, m, sec].map(n => String(n).padStart(2, '0')).join(':');
      }
    }
    setInterval(tick, 1000);
    tick();
  }

  function loadThresholds() {
    thresholds = Settings.getThresholds();
  }

  function llmThreshold() {
    return thresholds.llm_usage_percent || { warning: 80, critical: 90 };
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
    if (!el) return;
    if (state === 'connected') {
      el.classList.remove('disconnected');
    } else {
      el.classList.add('disconnected');
    }
  }

  // --- Fetch initial data via REST ---

  async function fetchInitialData() {
    try {
      const [metricsRes, configRes, cwRes, usageRes, copilotRes, ollamaRes] = await Promise.allSettled([
        fetch('/api/metrics'),
        fetch('/api/settings'),
        fetch('/api/claude-web-usage'),
        fetch('/api/usage'),
        fetch('/api/copilot-usage'),
        fetch('/api/ollama-usage'),
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
        const ollamaInput = document.getElementById('ollamaBaseUrl');
        if (ollamaInput) ollamaInput.value = config.ollama_base_url || DEFAULT_OLLAMA_BASE_URL;
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
        handleCopilotApi(data.data);
      }

      if (ollamaRes.status === 'fulfilled' && ollamaRes.value.ok) {
        const data = await ollamaRes.value.json();
        handleOllama(data.data);
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
      fill.classList.remove('skeleton');
    }
    if (val) {
      val.innerHTML = `${Math.round(pct)}<em>%</em>`;
      val.className = 'bar-value tnum';
    }
    if (card) {
      card.classList.remove('warn', 'crit');
      if (level === 'warning') card.classList.add('warn');
      if (level === 'critical') card.classList.add('crit');
    }

    // Update sparkline trend
    const trendId = 'trend' + fillId.replace(/^fill/, '');
    if (!trendData[trendId]) trendData[trendId] = [];
    trendData[trendId].push(pct);
    if (trendData[trendId].length > TREND_MAX) trendData[trendId].shift();
    updateTrend(trendId, trendData[trendId]);
  }

  function updateTrend(trendId, history) {
    const svg = document.getElementById(trendId);
    if (!svg || history.length < 2) return;
    const path = svg.querySelector('path');
    if (!path) return;
    const w = 80, h = 30;
    const dx = w / (history.length - 1);
    const d = history.map((v, i) => {
      const x = (i * dx).toFixed(1);
      const y = (h - Math.max(0, Math.min(100, v)) / 100 * h).toFixed(1);
      return (i === 0 ? 'M' : 'L') + x + ' ' + y;
    }).join('');
    path.setAttribute('d', d);
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
      const level = Charts.getLevel(item.pct, llmThreshold().warning, llmThreshold().critical);
      updateBar(item.fill, item.val, item.card, item.pct, level);

      const detailEl = document.getElementById(item.detail);
      if (detailEl && item.reset) {
        detailEl.textContent = item.reset;
      }
    }

    // Extra usage
    if (data.extra_usage) {
      const pct = data.extra_usage.used_percent;
      const used = data.extra_usage.used_usd;
      const limit = data.extra_usage.limit_usd;
      if (pct != null) {
        const level = Charts.getLevel(pct, llmThreshold().warning, llmThreshold().critical);
        updateBar('fillClaudeExtra', 'valClaudeExtra', 'cardClaudeExtra', pct, level);
      }
      const detailEl = document.getElementById('detailClaudeExtra');
      if (detailEl && used != null && limit != null) {
        detailEl.textContent = `$${used} / $${limit}`;
      }
    }
  }

  // --- Copilot API Usage Handler ---

  function handleCopilotApi(data) {
    if (!data) return;

    // Plan name
    const planEl = document.getElementById('copilotPlan');
    if (planEl && data.plan) {
      const planMap = { individual: 'PRO', business: 'BUSINESS', enterprise: 'ENTERPRISE' };
      planEl.textContent = planMap[data.plan] || data.plan.toUpperCase();
    }

    const quotas = data.quotas || [];
    const premium = quotas.find(q => q.quota_id === 'premium_interactions');
    if (premium) {
      const pct = premium.percent_used;
      const level = Charts.getLevel(pct, llmThreshold().warning, llmThreshold().critical);
      updateBar('fillCopilotPremium', 'valCopilotPremium', 'cardCopilotPremium', pct, level);

      const detailEl = document.getElementById('detailCopilotPremium');
      if (detailEl) {
        const used = premium.entitlement - premium.remaining;
        let text = `${used} / ${premium.entitlement}`;
        if (data.reset_date) text += ` · Resets ${data.reset_date}`;
        detailEl.textContent = text;
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

    // Forward nested copilot_api data
    if (data.copilot_api) {
      handleCopilotApi(data.copilot_api);
    }

    // Forward nested ollama data
    if (data.ollama) {
      handleOllama(data.ollama);
    }

    // Process per-provider token usages
    const usages = data.usages || [];
    for (const usage of usages) {
      if (usage.provider === 'codex') {
        handleCodexUsage(usage);
      }
      if (usage.provider === 'zhipuai') {
        handleZhipuaiUsage(usage);
      }
    }
  }

  // --- Codex Usage Handler ---

  function handleCodexUsage(usage) {
    if (!usage) return;

    if (usage.model === 'error') {
      ['detailCodexSession', 'detailCodexWeekly'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.textContent = usage.error || 'Token expired';
      });
      ['valCodexSession', 'valCodexWeekly'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.innerHTML = '--<em>%</em>';
      });
      return;
    }

    codexUsageState[usage.model] = usage;

    if (usage.plan_type) {
      const planEl = document.getElementById('codexPlan');
      if (planEl && !planEl.textContent) {
        planEl.textContent = usage.plan_type.toUpperCase();
      }
    }

    if (!document.getElementById('codexPlan')?.textContent) {
      const planEl = document.getElementById('codexPlan');
      if (planEl) planEl.textContent = 'PRO';
    }

    renderCodexSession();
    renderCodexWeekly();
  }

  function renderCodexSession() {
    const session = codexUsageState['session'];
    if (!session || session.quota_percentage == null) return;

    const level = Charts.getLevel(session.quota_percentage, llmThreshold().warning, llmThreshold().critical);
    updateBar('fillCodexSession', 'valCodexSession', 'cardCodexSession', session.quota_percentage, level);

    const detailEl = document.getElementById('detailCodexSession');
    if (detailEl) {
      detailEl.textContent = session.reset_text || '';
    }
  }

  function renderCodexWeekly() {
    const weekly = codexUsageState['weekly'];
    if (!weekly || weekly.quota_percentage == null) return;

    const level = Charts.getLevel(weekly.quota_percentage, llmThreshold().warning, llmThreshold().critical);
    updateBar('fillCodexWeekly', 'valCodexWeekly', 'cardCodexWeekly', weekly.quota_percentage, level);

    const detailParts = [];
    if (weekly.reset_text) detailParts.push(weekly.reset_text);

    const spark = codexUsageState['spark-weekly'];
    if (spark && spark.quota_percentage != null) {
      detailParts.push(`Spark: ${Math.round(spark.quota_percentage)}%`);
    }

    const review = codexUsageState['review'];
    if (review && review.quota_percentage != null) {
      detailParts.push(`Review: ${Math.round(review.quota_percentage)}%`);
    }

    const detailEl = document.getElementById('detailCodexWeekly');
    if (detailEl) {
      detailEl.textContent = detailParts.join(' · ');
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
      // MCP tool calls (5h rolling)
      if (pct != null) {
        const level = Charts.getLevel(pct, llmThreshold().warning, llmThreshold().critical);
        updateBar('fillZhipuaiMcp', 'valZhipuaiMcp', 'cardZhipuaiMcp', pct, level);
      }
      const detailEl = document.getElementById('detailZhipuaiMcp');
      if (detailEl) {
        const used = usage.total_tokens || 0;
        const limit = usage.quota_limit;
        let text = limit ? `${used.toLocaleString()} / ${limit.toLocaleString()}` : '';
        if (usage.reset_text) text = (text ? text + ' · ' : '') + usage.reset_text;
        detailEl.textContent = text;
      }
    } else if (model.startsWith('tokens-limit')) {
      // Monthly token usage
      if (pct != null) {
        const level = Charts.getLevel(pct, llmThreshold().warning, llmThreshold().critical);
        updateBar('fillZhipuaiTokens', 'valZhipuaiTokens', 'cardZhipuaiTokens', pct, level);
      }
      const detailEl = document.getElementById('detailZhipuaiTokens');
      if (detailEl && usage.reset_text) {
        detailEl.textContent = usage.reset_text;
      }
    }
  }

  // --- Ollama Handler ---

  function handleOllama(data) {
    if (!data) return;

    const card = document.getElementById('cardOllama');
    const valEl = document.getElementById('valOllama');
    const detailEl = document.getElementById('detailOllama');

    if (!data.available) {
      if (card) card.classList.add('idle');
      if (valEl) { valEl.textContent = 'offline'; valEl.className = 'bar-value muted'; }
      if (detailEl) detailEl.textContent = '';
      return;
    }

    if (!data.model) {
      if (card) card.classList.add('idle');
      if (valEl) { valEl.textContent = 'no model'; valEl.className = 'bar-value muted'; }
      if (detailEl) detailEl.textContent = '';
      return;
    }

    if (card) card.classList.remove('idle');

    if (valEl) {
      if (data.tok_per_sec != null) {
        valEl.innerHTML = data.tok_per_sec + '<em>tok/s</em>';
        valEl.className = 'bar-value tnum';
      } else {
        valEl.textContent = 'ready';
        valEl.className = 'bar-value muted';
      }
    }

    if (detailEl) {
      const parts = [data.model];
      if (data.vram_gb) parts.push(data.vram_gb + ' GB');
      if (data.benchmark_ago) parts.push(data.benchmark_ago);
      detailEl.textContent = parts.join(' · ');
    }
  }

  return { init, onConfigSaved };
})();

document.addEventListener('DOMContentLoaded', App.init);
