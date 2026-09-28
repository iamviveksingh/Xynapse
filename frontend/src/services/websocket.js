import { authFetch, getApiKey } from './api';

export class AlertWebSocketClient {
  constructor(onMessage, onStatusChange) {
    this.onMessage = onMessage;
    this.onStatusChange = onStatusChange;
    this.ws = null;
    this.reconnectTimer = null;
    this.pingInterval = null;
    this.isExplicitlyClosed = false;
  }

  async connect() {
    this.isExplicitlyClosed = false;
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    
    // Check if user is logged out before attempting ticket acquisition
    const apiKey = getApiKey();
    if (!apiKey) {
      if (this.onStatusChange) this.onStatusChange('AUTH_FAILED');
      return;
    }

    // Acquire single-use authentication ticket for secure stream access
    let ticket = '';
    try {
      const res = await authFetch('/api/alerts/ws-ticket', { method: 'POST' });
      if (res.ok) {
        const data = await res.json();
        ticket = data.ticket || '';
      } else if (res.status === 401 || res.status === 403) {
        console.warn(`[WS] Ticket rejected with HTTP ${res.status}`);
        if (this.onStatusChange) this.onStatusChange('AUTH_FAILED');
        return;
      }
    } catch (e) {
      console.warn('[WS] Ticket acquisition warning:', e);
      if (e?.isAuthError || e?.isForbidden) {
        if (this.onStatusChange) this.onStatusChange('AUTH_FAILED');
        return;
      }
    }

    if (!ticket) {
      console.warn('[WS] No ticket obtained; aborting WebSocket connection');
      if (this.onStatusChange) this.onStatusChange('AUTH_FAILED');
      return;
    }

    const wsUrl = `${protocol}//${window.location.host}/ws/alerts?ticket=${encodeURIComponent(ticket)}`;

    try {
      this.ws = new WebSocket(wsUrl);

      this.ws.onopen = () => {
        if (this.onStatusChange) this.onStatusChange('CONNECTED');
        // Heartbeat ping
        clearInterval(this.pingInterval);
        this.pingInterval = setInterval(() => {
          if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.ws.send('ping');
          }
        }, 15000);
      };

      this.ws.onmessage = (event) => {
        if (event.data === 'pong') return;
        try {
          const data = JSON.parse(event.data);
          if (this.onMessage) this.onMessage(data);
        } catch (e) {
          console.error('[WS] Parse error:', e);
        }
      };

      this.ws.onclose = () => {
        if (this.onStatusChange) this.onStatusChange('DISCONNECTED');
        clearInterval(this.pingInterval);
        if (!this.isExplicitlyClosed) {
          clearTimeout(this.reconnectTimer);
          this.reconnectTimer = setTimeout(() => this.connect(), 3000);
        }
      };

      this.ws.onerror = () => {
        if (this.onStatusChange) this.onStatusChange('ERROR');
        this.ws?.close();
      };
    } catch (err) {
      if (this.onStatusChange) this.onStatusChange('ERROR');
      if (!this.isExplicitlyClosed) {
        clearTimeout(this.reconnectTimer);
        this.reconnectTimer = setTimeout(() => this.connect(), 3000);
      }
    }
  }

  disconnect() {
    this.isExplicitlyClosed = true;
    clearInterval(this.pingInterval);
    clearTimeout(this.reconnectTimer);
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
  }
}
