/* ============================================
   Tiny Monitor — Settings UI
   ============================================ */

const Settings = (() => {
  let modal = null;
  let isOpen = false;

  const API_KEY_FIELDS = [
    { id: 'keyAnthropic', key: 'anthropic_api_key', provider: 'anthropic' },
    { id: 'keyAnthropicRegular', key: 'anthropic_api_key_regular', provider: 'anthropic_regular' },
    { id: 'keyOpenai', key: 'openai_api_key', provider: 'openai' },
    { id: 'keyGithub', key: 'github_token', provider: 'github' },
    { id: 'keyZhipuai', key: 'zhipuai_api_key', provider: 'zhipuai' },
    { id: 'keyGemini', key: 'gemini_api_key', provider: 'gemini' },
  ];

  function init() {
    modal = document.getElementById('settingsModal');

    document.getElementById('btnSettings').addEventListener('click', open);
    document.getElementById('btnCloseSettings').addEventListener('click', close);
    document.getElementById('modalBackdrop').addEventListener('click', close);
    document.getElementById('btnCancelSettings').addEventListener('click', close);
    document.getElementById('btnSaveSettings').addEventListener('click', save);

    // Escape key closes modal
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && isOpen) close();
    });
  }

  async function open() {
    isOpen = true;
    modal.classList.add('modal--open');
    await loadConfig();
  }

  function close() {
    isOpen = false;
    modal.classList.remove('modal--open');
  }

  async function loadConfig() {
    try {
      const res = await fetch('/api/config');
      if (!res.ok) return;
      const data = await res.json();

      // Load API key status — providers is an array: [{name, configured}, ...]
      if (Array.isArray(data.providers)) {
        for (const field of API_KEY_FIELDS) {
          const input = document.getElementById(field.id);
          if (!input) continue;
          const match = data.providers.find(p => p.name === field.provider);
          if (match && match.configured) {
            input.placeholder = '••••••••  (configured)';
          }
        }
      }

      // Load thresholds
      if (data.thresholds) {
        for (const t of data.thresholds) {
          const row = document.querySelector(`.threshold-field[data-metric="${t.metric}"]`);
          if (!row) continue;
          const warnInput = row.querySelector('[data-level="warning"]');
          const critInput = row.querySelector('[data-level="critical"]');
          if (warnInput) warnInput.value = t.warning;
          if (critInput) critInput.value = t.critical;
        }
      }

      // Load plan limits
      if (data.anthropic_session_limit) {
        document.getElementById('sessionLimit').value = data.anthropic_session_limit;
      }
      if (data.anthropic_weekly_limit) {
        document.getElementById('weeklyLimit').value = data.anthropic_weekly_limit;
      }

      // Load budget
      if (data.monthly_budget_usd) {
        document.getElementById('monthlyBudget').value = data.monthly_budget_usd;
      }

      // Load gateway
      if (data.gateway_url) {
        document.getElementById('gatewayUrl').value = data.gateway_url;
      }
      if (data.gateway_configured) {
        document.getElementById('gatewayKey').placeholder = '••••••••  (configured)';
      }
    } catch (e) {
      // Config endpoint not available yet
    }
  }

  async function save() {
    const config = { thresholds: [] };

    // Collect thresholds
    const thresholdFields = document.querySelectorAll('.threshold-field');
    thresholdFields.forEach((row) => {
      const metric = row.dataset.metric;
      const warning = parseFloat(row.querySelector('[data-level="warning"]').value) || 0;
      const critical = parseFloat(row.querySelector('[data-level="critical"]').value) || 0;
      config.thresholds.push({ metric, warning, critical });
    });

    // Collect API keys (only non-empty, so unchanged keys aren't overwritten)
    for (const field of API_KEY_FIELDS) {
      const val = document.getElementById(field.id).value.trim();
      if (val) {
        config[field.key] = val;
      }
    }

    // Plan limits
    const sessionVal = document.getElementById('sessionLimit').value.trim();
    if (sessionVal) config.anthropic_session_limit = parseInt(sessionVal);
    const weeklyVal = document.getElementById('weeklyLimit').value.trim();
    if (weeklyVal) config.anthropic_weekly_limit = parseInt(weeklyVal);

    // Budget
    const budgetVal = document.getElementById('monthlyBudget').value.trim();
    if (budgetVal) config.monthly_budget_usd = parseFloat(budgetVal);

    // Gateway settings
    const gwUrl = document.getElementById('gatewayUrl').value.trim();
    const gwKey = document.getElementById('gatewayKey').value.trim();
    if (gwUrl) config.gateway_url = gwUrl;
    if (gwKey) config.gateway_key = gwKey;

    try {
      const res = await fetch('/api/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(config),
      });
      if (res.ok) {
        close();
        if (typeof App !== 'undefined' && App.onConfigSaved) {
          App.onConfigSaved(config);
        }
      }
    } catch (e) {
      // Silently fail
    }
  }

  /**
   * Get current threshold values from the UI (for live checking).
   * @returns {Object<string, {warning: number, critical: number}>}
   */
  function getThresholds() {
    const result = {};
    const thresholdFields = document.querySelectorAll('.threshold-field');
    thresholdFields.forEach((row) => {
      const metric = row.dataset.metric;
      const warning = parseFloat(row.querySelector('[data-level="warning"]').value) || 0;
      const critical = parseFloat(row.querySelector('[data-level="critical"]').value) || 0;
      result[metric] = { warning, critical };
    });
    return result;
  }

  return { init, open, close, getThresholds };
})();
