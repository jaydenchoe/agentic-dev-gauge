/* ============================================
   Tiny Monitor — Charts & Visualization
   ============================================ */

const Charts = (() => {
  const CIRCUMFERENCE = 2 * Math.PI * 50; // r=50

  /**
   * Update an SVG circle gauge.
   * @param {string} gaugeId - The gauge container element ID
   * @param {number} percent - 0-100
   * @param {string} level - 'normal' | 'warning' | 'critical'
   */
  function updateGauge(gaugeId, percent, level) {
    const el = document.getElementById(gaugeId);
    if (!el) return;

    const fill = el.querySelector('.gauge__fill');
    const valueEl = el.querySelector('.gauge__value');

    const clamped = Math.max(0, Math.min(100, percent));
    const offset = CIRCUMFERENCE - (clamped / 100) * CIRCUMFERENCE;

    fill.style.strokeDasharray = CIRCUMFERENCE;
    fill.style.strokeDashoffset = offset;

    const colors = {
      normal: '#22c55e',
      warning: '#f59e0b',
      critical: '#ef4444',
    };
    fill.style.stroke = colors[level] || colors.normal;

    valueEl.innerHTML = `${Math.round(clamped)}<span class="gauge__unit">%</span>`;
  }

  /**
   * Update card threshold state (border color, alert icon).
   * @param {string} cardId - Card element ID
   * @param {string} level - 'normal' | 'warning' | 'critical'
   */
  function updateCardState(cardId, level) {
    const card = document.getElementById(cardId);
    if (!card) return;

    card.classList.remove('card--warning', 'card--critical');
    const icon = card.querySelector('.card__alert-icon');

    if (level === 'warning') {
      card.classList.add('card--warning');
      if (icon) { icon.textContent = '\u26A0'; icon.setAttribute('aria-label', 'Warning'); }
    } else if (level === 'critical') {
      card.classList.add('card--critical');
      if (icon) { icon.textContent = '\uD83D\uDD34'; icon.setAttribute('aria-label', 'Critical'); }
    } else {
      if (icon) { icon.textContent = ''; icon.removeAttribute('aria-label'); }
    }
  }

  // --- Sparkline ---

  const sparklineData = {};
  const MAX_POINTS = 60;

  /**
   * Push a data point and redraw a sparkline canvas.
   * @param {string} canvasId - Canvas element ID
   * @param {number} value - Value to push (0-100 typically)
   * @param {string} level - 'normal' | 'warning' | 'critical'
   */
  function pushSparkline(canvasId, value, level) {
    if (!sparklineData[canvasId]) {
      sparklineData[canvasId] = [];
    }
    const data = sparklineData[canvasId];
    data.push(value);
    if (data.length > MAX_POINTS) data.shift();

    drawSparkline(canvasId, data, level);
  }

  function drawSparkline(canvasId, data, level) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    const w = rect.width;
    const h = rect.height;

    canvas.width = w * dpr;
    canvas.height = h * dpr;
    ctx.scale(dpr, dpr);

    ctx.clearRect(0, 0, w, h);

    if (data.length < 2) return;

    const colors = {
      normal: { line: '#22c55e', fill: 'rgba(34,197,94,0.1)' },
      warning: { line: '#f59e0b', fill: 'rgba(245,158,11,0.1)' },
      critical: { line: '#ef4444', fill: 'rgba(239,68,68,0.1)' },
    };
    const c = colors[level] || colors.normal;

    const max = Math.max(100, ...data);
    const stepX = w / (MAX_POINTS - 1);
    const startIdx = MAX_POINTS - data.length;

    ctx.beginPath();
    for (let i = 0; i < data.length; i++) {
      const x = (startIdx + i) * stepX;
      const y = h - (data[i] / max) * (h - 4) - 2;
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }

    // Fill
    ctx.strokeStyle = 'transparent';
    ctx.lineTo((startIdx + data.length - 1) * stepX, h);
    ctx.lineTo(startIdx * stepX, h);
    ctx.closePath();
    ctx.fillStyle = c.fill;
    ctx.fill();

    // Line
    ctx.beginPath();
    for (let i = 0; i < data.length; i++) {
      const x = (startIdx + i) * stepX;
      const y = h - (data[i] / max) * (h - 4) - 2;
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.strokeStyle = c.line;
    ctx.lineWidth = 1.5;
    ctx.lineJoin = 'round';
    ctx.stroke();
  }

  /**
   * Format bytes/sec into human-readable string.
   */
  function formatBytes(bytes) {
    if (bytes < 1024) return bytes.toFixed(0) + ' B/s';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB/s';
    return (bytes / (1024 * 1024)).toFixed(1) + ' MB/s';
  }

  /**
   * Format token counts.
   */
  function formatTokens(count) {
    if (count < 1000) return String(count);
    if (count < 1_000_000) return (count / 1000).toFixed(1) + 'K';
    return (count / 1_000_000).toFixed(2) + 'M';
  }

  /**
   * Determine threshold level for a value.
   * @param {number} value
   * @param {number} warning
   * @param {number} critical
   * @returns {'normal'|'warning'|'critical'}
   */
  function getLevel(value, warning, critical) {
    if (value >= critical) return 'critical';
    if (value >= warning) return 'warning';
    return 'normal';
  }

  return {
    updateGauge,
    updateCardState,
    pushSparkline,
    formatBytes,
    formatTokens,
    getLevel,
  };
})();
