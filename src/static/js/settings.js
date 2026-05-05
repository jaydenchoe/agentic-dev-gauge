/* ============================================
   Agentic Dev Gauge — Settings UI
   ============================================ */

const Settings = (() => {
  let modal = null;
  let isOpen = false;
  const DEFAULT_OLLAMA_BASE_URL = 'http://127.0.0.1:11434';
  const DEFAULT_LM_STUDIO_BASE_URL = 'http://127.0.0.1:1234';
  const DEFAULT_GEEKMAGIC_URL = 'http://192.168.150.113';

  const API_KEY_FIELDS = [
    { id: 'keyCodex', key: 'codex_api_key', provider: 'codex' },
    { id: 'keyZhipuai', key: 'zhipuai_api_key', provider: 'zhipuai' },
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
    modal.classList.add('open');
    await loadConfig();
  }

  function close() {
    isOpen = false;
    modal.classList.remove('open');
  }

  async function loadConfig() {
    try {
      const res = await fetch('/api/settings');
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

      // Load gateway
      document.getElementById('ollamaBaseUrl').value = data.ollama_base_url || DEFAULT_OLLAMA_BASE_URL;
      document.getElementById('lmStudioBaseUrl').value = data.lm_studio_base_url || DEFAULT_LM_STUDIO_BASE_URL;
      if (data.gateway_url) {
        document.getElementById('gatewayUrl').value = data.gateway_url;
      }
      if (data.gateway_configured) {
        document.getElementById('gatewayKey').placeholder = '••••••••  (configured)';
      }
      document.getElementById('geekmagicUltraUrl').value =
        data.geekmagic_ultra_url || DEFAULT_GEEKMAGIC_URL;
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

    // Gateway settings
    const ollamaBaseUrl = document.getElementById('ollamaBaseUrl').value.trim();
    const lmStudioBaseUrl = document.getElementById('lmStudioBaseUrl').value.trim();
    const gwUrl = document.getElementById('gatewayUrl').value.trim();
    const gwKey = document.getElementById('gatewayKey').value.trim();
    const geekmagicUrl = document.getElementById('geekmagicUltraUrl').value.trim();
    config.ollama_base_url = ollamaBaseUrl || DEFAULT_OLLAMA_BASE_URL;
    config.lm_studio_base_url = lmStudioBaseUrl || DEFAULT_LM_STUDIO_BASE_URL;
    if (gwUrl) config.gateway_url = gwUrl;
    if (gwKey) config.gateway_key = gwKey;
    config.geekmagic_ultra_url = geekmagicUrl;

    try {
      const res = await fetch('/api/settings', {
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
