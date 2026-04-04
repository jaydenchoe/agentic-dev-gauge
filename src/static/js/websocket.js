/* ============================================
   Agentic Coding Gauge — WebSocket Client
   ============================================ */

class MonitorWebSocket {
  constructor(url) {
    this.url = url;
    this.ws = null;
    this.reconnectDelay = 1000;
    this.maxReconnectDelay = 30000;
    this.listeners = {
      system_metrics: [],
      usage_update: [],
      alert: [],
      claude_web: [],
      open: [],
      close: [],
    };
    this._reconnectTimer = null;
    this._intentionallyClosed = false;
  }

  connect() {
    this._intentionallyClosed = false;
    try {
      this.ws = new WebSocket(this.url);
    } catch (e) {
      this._scheduleReconnect();
      return;
    }

    this.ws.onopen = () => {
      this.reconnectDelay = 1000;
      // Subscribe to all channels
      this.ws.send(JSON.stringify({
        type: 'subscribe',
        channels: ['system_metrics', 'usage_update', 'alert', 'claude_web'],
      }));
      this._emit('open', null);
    };

    this.ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        this._emit(msg.type, msg.data);
      } catch (e) {
        // Ignore malformed messages
      }
    };

    this.ws.onclose = () => {
      this._emit('close', null);
      if (!this._intentionallyClosed) {
        this._scheduleReconnect();
      }
    };

    this.ws.onerror = () => {
      this.ws.close();
    };
  }

  on(type, callback) {
    if (!this.listeners[type]) {
      this.listeners[type] = [];
    }
    this.listeners[type].push(callback);
  }

  off(type, callback) {
    const list = this.listeners[type];
    if (list) {
      this.listeners[type] = list.filter(fn => fn !== callback);
    }
  }

  disconnect() {
    this._intentionallyClosed = true;
    if (this._reconnectTimer) {
      clearTimeout(this._reconnectTimer);
      this._reconnectTimer = null;
    }
    if (this.ws) {
      this.ws.close();
    }
  }

  _emit(type, data) {
    const list = this.listeners[type];
    if (list) {
      list.forEach(fn => fn(data));
    }
  }

  _scheduleReconnect() {
    this._reconnectTimer = setTimeout(() => {
      this.reconnectDelay = Math.min(this.reconnectDelay * 2, this.maxReconnectDelay);
      this.connect();
    }, this.reconnectDelay);
  }
}
