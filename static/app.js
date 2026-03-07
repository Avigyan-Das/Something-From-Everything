/**
 * Something from Everything — Dashboard Frontend
 * Real-time dashboard with WebSocket updates
 */

// ─── State ──────────────────────────────────────────────────────

let ws = null;
let wsReconnectInterval = null;
const API = '';  // Same origin

// ─── Initialize ─────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
    connectWebSocket();
    refreshAll();

    // Auto-refresh every 60 seconds
    setInterval(refreshStats, 60000);
});

// ─── API Helpers ────────────────────────────────────────────────

async function api(endpoint, options = {}) {
    try {
        const response = await fetch(`${API}${endpoint}`, {
            headers: { 'Content-Type': 'application/json' },
            ...options
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return await response.json();
    } catch (error) {
        console.error(`API error [${endpoint}]:`, error);
        return null;
    }
}

// ─── WebSocket ──────────────────────────────────────────────────

function connectWebSocket() {
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${location.host}/ws/live`;

    try {
        ws = new WebSocket(wsUrl);

        ws.onopen = () => {
            updateWsStatus(true);
            showToast('Connected to live feed', 'success');
            if (wsReconnectInterval) {
                clearInterval(wsReconnectInterval);
                wsReconnectInterval = null;
            }
        };

        ws.onmessage = (event) => {
            try {
                const msg = JSON.parse(event.data);
                handleWsMessage(msg);
            } catch (e) {
                console.error('WS parse error:', e);
            }
        };

        ws.onclose = () => {
            updateWsStatus(false);
            // Auto-reconnect
            if (!wsReconnectInterval) {
                wsReconnectInterval = setInterval(() => {
                    if (!ws || ws.readyState === WebSocket.CLOSED) {
                        connectWebSocket();
                    }
                }, 5000);
            }
        };

        ws.onerror = () => {
            updateWsStatus(false);
        };
    } catch (e) {
        updateWsStatus(false);
    }
}

function handleWsMessage(msg) {
    switch (msg.type) {
        case 'stats':
            updateStats(msg.data);
            break;
        case 'collection_complete':
            showToast(`Collection complete: ${JSON.stringify(msg.data.results || {})}`, 'success');
            refreshAll();
            break;
        case 'analysis_complete':
            showToast(`Analysis complete: ${msg.data.analytics_insights || 0} insights`, 'info');
            refreshAll();
            break;
        case 'pong':
            break;
    }
}

function updateWsStatus(connected) {
    const dot = document.getElementById('ws-dot');
    const text = document.getElementById('ws-status-text');
    dot.className = `status-dot ${connected ? 'online' : 'offline'}`;
    text.textContent = connected ? 'Live' : 'Disconnected';
}

// ─── Refresh ────────────────────────────────────────────────────

async function refreshAll() {
    await Promise.all([
        refreshStats(),
        refreshDataFeed(),
        refreshInsights(),
        refreshAlerts(),
        refreshSources()
    ]);
}

async function refreshStats() {
    const data = await api('/api/stats');
    if (data) {
        updateStats(data);
    }
}

function updateStats(stats) {
    animateNumber('stat-data', stats.total_data_items || 0);
    animateNumber('stat-insights', stats.total_insights || 0);
    animateNumber('stat-alerts', stats.active_alerts || 0);
    animateNumber('stat-sources', stats.sources_active || 0);

    // Update LLM status
    const llmDot = document.getElementById('llm-dot');
    const llmText = document.getElementById('llm-status-text');
    const llmConnected = stats.llm_status === 'connected';
    llmDot.className = `status-dot ${llmConnected ? 'online' : 'warning'}`;
    llmText.textContent = llmConnected ? 'LLM Online' : 'LLM Offline';
}

function animateNumber(elementId, target) {
    const el = document.getElementById(elementId);
    if (!el) return;

    const current = parseInt(el.textContent) || 0;
    if (current === target) return;

    const diff = target - current;
    const steps = Math.min(Math.abs(diff), 20);
    const stepSize = diff / steps;
    let step = 0;

    const interval = setInterval(() => {
        step++;
        if (step >= steps) {
            el.textContent = target.toLocaleString();
            clearInterval(interval);
        } else {
            el.textContent = Math.round(current + stepSize * step).toLocaleString();
        }
    }, 30);
}

// ─── Data Feed ──────────────────────────────────────────────────

async function refreshDataFeed() {
    const data = await api('/api/data?limit=30');
    const container = document.getElementById('data-feed');
    const badge = document.getElementById('feed-count');

    if (!data || !data.items || data.items.length === 0) {
        container.innerHTML = `
            <div class="empty-state">
                <div class="empty-icon">📡</div>
                <div class="empty-text">No data collected yet</div>
                <div class="empty-hint">Click "Collect Now" to start gathering data</div>
            </div>`;
        badge.textContent = '0';
        return;
    }

    badge.textContent = data.count;
    container.innerHTML = data.items.map(item => renderFeedItem(item)).join('');
}

function renderFeedItem(item) {
    const title = escapeHtml(item.title || 'Untitled');
    const source = item.source || 'unknown';
    const category = item.category || 'general';
    const time = formatTime(item.collected_at);
    const url = item.url || '#';

    return `
        <div class="feed-item">
            <div class="feed-item-header">
                <div class="feed-item-title">
                    <a href="${url}" target="_blank" rel="noopener">${title}</a>
                </div>
            </div>
            <div class="feed-item-meta">
                <span class="source-tag ${source}">${source.replace('_', ' ')}</span>
                <span>${category.replace('_', ' ')}</span>
                <span>${time}</span>
            </div>
        </div>
    `;
}

// ─── Insights ───────────────────────────────────────────────────

async function refreshInsights() {
    const data = await api('/api/insights?limit=20');
    const container = document.getElementById('insights-panel');
    const badge = document.getElementById('insight-count');

    if (!data || !data.insights || data.insights.length === 0) {
        container.innerHTML = `
            <div class="empty-state">
                <div class="empty-icon">💡</div>
                <div class="empty-text">No insights yet</div>
                <div class="empty-hint">Collect data and run analysis to discover patterns</div>
            </div>`;
        badge.textContent = '0';
        return;
    }

    badge.textContent = data.count;
    container.innerHTML = data.insights.map(insight => renderInsightCard(insight)).join('');
}

function renderInsightCard(insight) {
    const title = escapeHtml(insight.title || 'Insight');
    const desc = escapeHtml((insight.description || '').substring(0, 300));
    const severity = insight.severity || 'info';
    const confidence = Math.round((insight.confidence || 0) * 100);
    const domains = (Array.isArray(insight.domains) ? insight.domains : []);
    const type = insight.insight_type || 'unknown';

    return `
        <div class="insight-card ${severity}">
            <div class="insight-title">${title}</div>
            <div class="insight-desc">${desc}</div>
            <div class="insight-meta">
                <span class="severity-badge ${severity}">${severity}</span>
                <div class="confidence-bar">
                    <span>Confidence:</span>
                    <div class="confidence-bar-track">
                        <div class="confidence-bar-fill" style="width: ${confidence}%"></div>
                    </div>
                    <span>${confidence}%</span>
                </div>
                <div class="domain-tags">
                    ${domains.map(d => `<span class="domain-tag">${d}</span>`).join('')}
                </div>
            </div>
        </div>
    `;
}

// ─── Alerts ─────────────────────────────────────────────────────

async function refreshAlerts() {
    const data = await api('/api/alerts?limit=20');
    const container = document.getElementById('alerts-panel');
    const badge = document.getElementById('alert-count');

    if (!data || !data.alerts || data.alerts.length === 0) {
        container.innerHTML = `
            <div class="empty-state">
                <div class="empty-icon">🔔</div>
                <div class="empty-text">No alerts</div>
                <div class="empty-hint">Alerts will appear when significant patterns are detected</div>
            </div>`;
        badge.textContent = '0';
        return;
    }

    badge.textContent = data.count;
    container.innerHTML = data.alerts.map(alert => renderAlertItem(alert)).join('');
}

function renderAlertItem(alert) {
    const title = escapeHtml(alert.title || 'Alert');
    const message = escapeHtml((alert.message || '').substring(0, 200));
    const severity = alert.severity || 'info';
    const time = formatTime(alert.created_at);
    const acked = alert.acknowledged;

    const icons = { critical: '🚨', high: '⚠️', medium: 'ℹ️', low: '📋', info: '📌' };
    const icon = icons[severity] || '📌';

    return `
        <div class="alert-item ${severity}">
            <span class="alert-icon">${icon}</span>
            <div class="alert-content">
                <div class="alert-title">${title}</div>
                <div class="alert-message">${message}</div>
                <div class="alert-time">${time}</div>
            </div>
            ${!acked ? `<button class="alert-ack-btn" onclick="acknowledgeAlert('${alert.id}')">Acknowledge</button>` : ''}
        </div>
    `;
}

async function acknowledgeAlert(alertId) {
    await api(`/api/alerts/${alertId}/acknowledge`, { method: 'POST' });
    showToast('Alert acknowledged', 'success');
    refreshAlerts();
    refreshStats();
}

// ─── Sources ────────────────────────────────────────────────────

async function refreshSources() {
    const data = await api('/api/sources');
    const container = document.getElementById('sources-panel');

    if (!data || !data.sources || data.sources.length === 0) {
        container.innerHTML = `
            <div class="empty-state">
                <div class="empty-text">No sources configured</div>
            </div>`;
        return;
    }

    const sourceIcons = {
        rss: '📰', web_scraper: '🕷️', social: '💬',
        finance: '📈', weather: '🌤️'
    };

    container.innerHTML = `
        <div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 1rem;">
            ${data.sources.map(src => `
                <div class="feed-item" style="margin: 0;">
                    <div class="feed-item-header">
                        <div class="feed-item-title">
                            ${sourceIcons[src.type] || '🔌'} ${src.name}
                        </div>
                    </div>
                    <div class="feed-item-meta">
                        <span class="source-tag ${src.type}">${src.enabled ? 'Active' : 'Disabled'}</span>
                    </div>
                </div>
            `).join('')}
        </div>
    `;
}

// ─── Actions ────────────────────────────────────────────────────

async function triggerCollection() {
    const btn = document.getElementById('btn-collect');
    btn.disabled = true;
    btn.innerHTML = '<span class="loading-spinner"></span> Collecting...';

    showToast('Starting data collection...', 'info');

    try {
        const data = await api('/api/collect/now', { method: 'POST' });
        if (data) {
            const total = Object.values(data.results || {}).reduce((sum, val) =>
                sum + (typeof val === 'number' ? val : 0), 0);
            showToast(`Collected ${total} items from ${Object.keys(data.results || {}).length} sources`, 'success');
            await refreshAll();
        }
    } catch (e) {
        showToast('Collection failed', 'error');
    }

    btn.disabled = false;
    btn.innerHTML = '⚡ Collect Now';
}

async function triggerAnalysis() {
    const btn = document.getElementById('btn-analyze');
    btn.disabled = true;
    btn.innerHTML = '<span class="loading-spinner"></span> Analyzing...';

    showToast('Running analysis pipeline...', 'info');

    try {
        const data = await api('/api/analyze/now', { method: 'POST' });
        if (data && data.results) {
            const r = data.results;
            showToast(`Analysis complete: ${r.analytics_insights || 0} insights, ${r.alerts_generated || 0} alerts`, 'success');
            await refreshAll();
        }
    } catch (e) {
        showToast('Analysis failed', 'error');
    }

    btn.disabled = false;
    btn.innerHTML = '🧠 Analyze Now';
}

// ─── Toast Notifications ────────────────────────────────────────

function showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;

    const icons = { success: '✓', error: '✗', info: 'ℹ' };
    toast.innerHTML = `<strong>${icons[type] || 'ℹ'}</strong> ${escapeHtml(message)}`;

    container.appendChild(toast);

    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateX(40px)';
        toast.style.transition = '0.3s ease';
        setTimeout(() => toast.remove(), 300);
    }, 4000);
}

// ─── Utilities ──────────────────────────────────────────────────

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function formatTime(dateStr) {
    if (!dateStr) return '';
    try {
        const date = new Date(dateStr);
        const now = new Date();
        const diffMs = now - date;
        const diffMin = Math.floor(diffMs / 60000);
        const diffHr = Math.floor(diffMs / 3600000);
        const diffDay = Math.floor(diffMs / 86400000);

        if (diffMin < 1) return 'just now';
        if (diffMin < 60) return `${diffMin}m ago`;
        if (diffHr < 24) return `${diffHr}h ago`;
        if (diffDay < 7) return `${diffDay}d ago`;

        return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
    } catch {
        return dateStr;
    }
}
