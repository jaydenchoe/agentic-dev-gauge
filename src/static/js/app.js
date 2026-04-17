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
  const DEFAULT_OLLAMA2_BASE_URL = '';
  const DEFAULT_OLLAMA3_BASE_URL = '';

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
    if (config && Object.prototype.hasOwnProperty.call(config, 'ollama2_base_url')) {
      setOllamaCardVisibility('cardOllama2', config.ollama2_base_url || DEFAULT_OLLAMA2_BASE_URL);
    }
    if (config && Object.prototype.hasOwnProperty.call(config, 'ollama3_base_url')) {
      setOllamaCardVisibility('cardOllama3', config.ollama3_base_url || DEFAULT_OLLAMA3_BASE_URL);
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
      const [metricsRes, configRes, cwRes, usageRes, copilotRes, ollamaRes, ollama2Res, ollama3Res] = await Promise.allSettled([
        fetch('/api/metrics'),
        fetch('/api/settings'),
        fetch('/api/claude-web-usage'),
        fetch('/api/usage'),
        fetch('/api/copilot-usage'),
        fetch('/api/ollama-usage'),
        fetch('/api/ollama2-usage'),
        fetch('/api/ollama3-usage'),
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
        if (ollamaInput) {
          ollamaInput.value = config.ollama_base_url || DEFAULT_OLLAMA_BASE_URL;
        }
        const ollama2Input = document.getElementById('ollama2BaseUrl');
        if (ollama2Input) {
          ollama2Input.value = config.ollama2_base_url || DEFAULT_OLLAMA2_BASE_URL;
        }
        const ollama3Input = document.getElementById('ollama3BaseUrl');
        if (ollama3Input) {
          ollama3Input.value = config.ollama3_base_url || DEFAULT_OLLAMA3_BASE_URL;
        }
        setOllamaCardVisibility('cardOllama2', config.ollama2_base_url || DEFAULT_OLLAMA2_BASE_URL);
        setOllamaCardVisibility('cardOllama3', config.ollama3_base_url || DEFAULT_OLLAMA3_BASE_URL);
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

      if (ollama2Res.status === 'fulfilled' && ollama2Res.value.ok) {
        const data = await ollama2Res.value.json();
        handleOllama2(data.data);
      }

      if (ollama3Res.status === 'fulfilled' && ollama3Res.value.ok) {
        const data = await ollama3Res.value.json();
        handleOllama3(data.data);
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

    if (data.ollama2) {
      handleOllama2(data.ollama2);
    }

    if (data.ollama3) {
      handleOllama3(data.ollama3);
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
        if (el) el.innerHTML = '--<span class="bar__unit">%</span>';
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
      return;
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

  function clearOllamaCard(cardId, fillEl) {
    if (fillEl) {
      fillEl.style.width = '0%';
      fillEl.className = 'bar__fill bar__fill--skeleton';
    }

    const cardEl = document.getElementById(cardId);
    if (cardEl) {
      cardEl.className = cardEl.className.replace(/\s*card--(warning|critical)/g, '');
    }
  }

  function setOllamaCardVisibility(cardId, baseUrl) {
    const cardEl = document.getElementById(cardId);
    if (!cardEl) return;
    cardEl.style.display = baseUrl && baseUrl.trim() ? '' : 'none';
  }

  function setOllamaLabel(cardId, label, model) {
    const labelEl = document.querySelector(`#${cardId} .bar__label`);
    if (!labelEl) return;
    labelEl.textContent = model ? `${label} · ${model}` : label;
  }

  function handleOllama(data) {
    if (!data) return;

    const fillEl = document.getElementById('fillOllama');
    const valEl = document.getElementById('valOllama');
    const detailEl = document.getElementById('detailOllama');
    const baseUrlLabel = formatOllamaBaseUrl(data.base_url);

    if (!data.available) {
      setOllamaLabel('cardOllama', baseUrlLabel);
      clearOllamaCard('cardOllama', fillEl);
      if (valEl) { valEl.textContent = 'offline'; valEl.className = 'bar__value bar__value--muted'; }
      if (detailEl) detailEl.textContent = '';
      return;
    }

    if (!data.model) {
      setOllamaLabel('cardOllama', baseUrlLabel);
      clearOllamaCard('cardOllama', fillEl);
      if (valEl) { valEl.textContent = 'no model'; valEl.className = 'bar__value bar__value--muted'; }
      if (detailEl) detailEl.textContent = '';
      return;
    }

    setOllamaLabel('cardOllama', data.model);
    clearOllamaCard('cardOllama', fillEl);

    if (valEl) {
      if (data.tok_per_sec != null) {
        valEl.innerHTML = data.tok_per_sec + ' <span class="bar__unit">tok/s</span>';
        valEl.className = 'bar__value';
      } else {
        valEl.innerHTML = '-- <span class="bar__unit">tok/s</span>';
        valEl.className = 'bar__value bar__value--muted';
      }
    }

    if (detailEl) {
      detailEl.textContent = baseUrlLabel + (data.benchmark_ago ? ` · ${data.benchmark_ago}` : '');
    }
  }

  function handleOllama2(data) {
    if (!data) return;

    setOllamaCardVisibility('cardOllama2', data.base_url);

    const fillEl = document.getElementById('fillOllama2');
    const valEl = document.getElementById('valOllama2');
    const detailEl = document.getElementById('detailOllama2');
    const baseUrlLabel = formatOllamaBaseUrl(data.base_url);

    if (!data.available) {
      setOllamaLabel('cardOllama2', baseUrlLabel);
      clearOllamaCard('cardOllama2', fillEl);
      if (valEl) { valEl.textContent = 'offline'; valEl.className = 'bar__value bar__value--muted'; }
      if (detailEl) detailEl.textContent = '';
      return;
    }

    if (!data.model) {
      setOllamaLabel('cardOllama2', baseUrlLabel);
      clearOllamaCard('cardOllama2', fillEl);
      if (valEl) { valEl.textContent = 'no model'; valEl.className = 'bar__value bar__value--muted'; }
      if (detailEl) detailEl.textContent = '';
      return;
    }

    setOllamaLabel('cardOllama2', data.model);
    clearOllamaCard('cardOllama2', fillEl);

    if (valEl) {
      if (data.tok_per_sec != null) {
        valEl.innerHTML = data.tok_per_sec + ' <span class="bar__unit">tok/s</span>';
        valEl.className = 'bar__value';
      } else {
        valEl.innerHTML = '-- <span class="bar__unit">tok/s</span>';
        valEl.className = 'bar__value bar__value--muted';
      }
    }

    if (detailEl) {
      detailEl.textContent = baseUrlLabel + (data.benchmark_ago ? ` · ${data.benchmark_ago}` : '');
    }
  }

  function handleOllama3(data) {
    if (!data) return;

    setOllamaCardVisibility('cardOllama3', data.base_url);

    const fillEl = document.getElementById('fillOllama3');
    const valEl = document.getElementById('valOllama3');
    const detailEl = document.getElementById('detailOllama3');
    const baseUrlLabel = formatOllamaBaseUrl(data.base_url);

    if (!data.available) {
      setOllamaLabel('cardOllama3', baseUrlLabel);
      clearOllamaCard('cardOllama3', fillEl);
      if (valEl) { valEl.textContent = 'offline'; valEl.className = 'bar__value bar__value--muted'; }
      if (detailEl) detailEl.textContent = '';
      return;
    }

    if (!data.model) {
      setOllamaLabel('cardOllama3', baseUrlLabel);
      clearOllamaCard('cardOllama3', fillEl);
      if (valEl) { valEl.textContent = 'no model'; valEl.className = 'bar__value bar__value--muted'; }
      if (detailEl) detailEl.textContent = '';
      return;
    }

    setOllamaLabel('cardOllama3', data.model);
    clearOllamaCard('cardOllama3', fillEl);

    if (valEl) {
      if (data.tok_per_sec != null) {
        valEl.innerHTML = data.tok_per_sec + ' <span class="bar__unit">tok/s</span>';
        valEl.className = 'bar__value';
      } else {
        valEl.innerHTML = '-- <span class="bar__unit">tok/s</span>';
        valEl.className = 'bar__value bar__value--muted';
      }
    }

    if (detailEl) {
      detailEl.textContent = baseUrlLabel + (data.benchmark_ago ? ` · ${data.benchmark_ago}` : '');
    }
  }

  function formatOllamaBaseUrl(baseUrl) {
    if (!baseUrl) return '';
    try {
      const parsed = new URL(baseUrl.includes('://') ? baseUrl : `http://${baseUrl}`);
      if (parsed.hostname === '127.0.0.1' || parsed.hostname === 'localhost') {
        return 'local';
      }
      const port = parsed.port || (parsed.protocol === 'https:' ? '443' : '80');
      return `${parsed.hostname}:${port}`;
    } catch (e) {
      return baseUrl;
    }
  }

  return { init, onConfigSaved };
})();

document.addEventListener('DOMContentLoaded', App.init);
