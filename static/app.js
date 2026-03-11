/**
 * Something from Everything — 3D Intelligence Dashboard
 * Full-screen interactive 3D force-directed graph
 */

/* ═══════════════════════════════════════════════════════════
   State
   ═══════════════════════════════════════════════════════════ */

let G = null;           // ForceGraph3D instance
let ws = null;          // WebSocket
let wsTimer = null;     // reconnect timer
const API = '';

/* ═══════════════════════════════════════════════════════════
   Boot
   ═══════════════════════════════════════════════════════════ */

document.addEventListener('DOMContentLoaded', () => {
    buildGraph();
    connectWS();
    loadData();
    setInterval(() => refreshStats(), 60000);
});

/* ═══════════════════════════════════════════════════════════
   API Helper
   ═══════════════════════════════════════════════════════════ */

async function api(path, opts = {}) {
    try {
        const r = await fetch(API + path, { headers: { 'Content-Type': 'application/json' }, ...opts });
        if (!r.ok) throw new Error(r.status);
        return await r.json();
    } catch (e) { console.warn('api', path, e); return null; }
}

/* ═══════════════════════════════════════════════════════════
   3D Graph — Initialize
   ═══════════════════════════════════════════════════════════ */

function buildGraph() {
    const el = document.getElementById('3d-graph');

    G = ForceGraph3D()(el)
        .backgroundColor('#060610')
        .showNavInfo(false)
        .nodeThreeObject(n => makeNode(n))
        .nodeThreeObjectExtend(false)
        .nodeLabel(n => buildTooltip(n))
        .onNodeClick(n => onClickNode(n))
        .linkWidth(l => l.strong ? 1.8 : 0.4)
        .linkOpacity(0.6)
        .linkColor(l => l.color || 'rgba(255,255,255,0.15)')
        .linkDirectionalParticles(l => l.strong ? 3 : 0)
        .linkDirectionalParticleWidth(1.5)
        .linkDirectionalParticleSpeed(0.006)
        .linkDirectionalParticleColor(() => '#00d4ff')
        .width(window.innerWidth)
        .height(window.innerHeight);

    // Tweak forces
    G.d3Force('charge').strength(-80);
    G.d3Force('link').distance(l => l.strong ? 60 : 120);

    // Stars backdrop
    const starGeo = new THREE.BufferGeometry();
    const verts = [];
    for (let i = 0; i < 3000; i++) {
        verts.push(
            (Math.random() - 0.5) * 4000,
            (Math.random() - 0.5) * 4000,
            (Math.random() - 0.5) * 4000
        );
    }
    starGeo.setAttribute('position', new THREE.Float32BufferAttribute(verts, 3));
    const starMat = new THREE.PointsMaterial({ color: 0x555577, size: 1.5, transparent: true, opacity: 0.7 });
    G.scene().add(new THREE.Points(starGeo, starMat));

    // Add ambient light so MeshPhong / MeshLambert materials are visible
    G.scene().add(new THREE.AmbientLight(0xcccccc, 1.2));
    G.scene().add(new THREE.DirectionalLight(0xffffff, 0.8));

    window.addEventListener('resize', () => {
        G.width(window.innerWidth);
        G.height(window.innerHeight);
    });
}

/* ═══════════════════════════════════════════════════════════
   Node Meshes
   ═══════════════════════════════════════════════════════════ */

const SEV_COLORS = {
    critical: 0xef4444,
    high: 0xf59e0b,
    medium: 0x00d4ff,
    low: 0xa855f7,
    info: 0x9090a8
};
const SRC_MAP = {
    rss: { color: 0x00d4ff, make: () => new THREE.SphereGeometry(3.5, 24, 24) },
    reddit: { color: 0xec4899, make: () => new THREE.BoxGeometry(5, 5, 5) },
    hackernews: { color: 0xf59e0b, make: () => new THREE.TorusGeometry(3.5, 1.2, 8, 20) },
    finance_api: { color: 0x10b981, make: () => new THREE.ConeGeometry(3.5, 7, 6) },
    weather_api: { color: 0xa855f7, make: () => new THREE.IcosahedronGeometry(3.5) },
    web_scraper: { color: 0xef4444, make: () => new THREE.OctahedronGeometry(3.5) }
};

function makeNode(n) {
    const group = new THREE.Group();

    if (n._isInsight) {
        const c = SEV_COLORS[n.severity] || SEV_COLORS.info;

        // Core sphere
        const core = new THREE.Mesh(
            new THREE.SphereGeometry(9, 32, 32),
            new THREE.MeshPhongMaterial({ color: c, emissive: c, emissiveIntensity: 0.55, transparent: true, opacity: 0.92 })
        );
        group.add(core);

        // Halo glow
        const halo = new THREE.Mesh(
            new THREE.SphereGeometry(14, 32, 32),
            new THREE.MeshBasicMaterial({ color: c, transparent: true, opacity: 0.12, side: THREE.BackSide })
        );
        group.add(halo);

        // Outer ring
        const ring = new THREE.Mesh(
            new THREE.TorusGeometry(16, 0.4, 16, 60),
            new THREE.MeshBasicMaterial({ color: c, transparent: true, opacity: 0.25 })
        );
        ring.rotation.x = Math.PI / 2;
        group.add(ring);

        // Animate: slow rotation
        group.userData.animate = (t) => {
            ring.rotation.z = t * 0.3;
            halo.scale.setScalar(1 + Math.sin(t * 2) * 0.06);
        };

    } else {
        let s;
        if (n.metadata?.pipeline === 'certstream_keyword_monitor') {
            s = { color: 0x39ff14, make: () => new THREE.CylinderGeometry(2, 2, 8, 16) }; // Neon green cylinder
        } else if (n.metadata?.pipeline === 'gdelt_extremes') {
            s = { color: 0xff4500, make: () => new THREE.SphereGeometry(4.5, 16, 16) };  // OrangeRed larger sphere
        } else if (n.metadata?.pipeline === 'openphish_tld_aggregation') {
            s = { color: 0x8a2be2, make: () => new THREE.DodecahedronGeometry(3.5) };      // Purple dodecahedron
        } else {
            s = SRC_MAP[n.source] || SRC_MAP.rss;
        }

        const mesh = new THREE.Mesh(
            s.make(),
            new THREE.MeshLambertMaterial({ color: s.color, transparent: true, opacity: 0.85 })
        );
        group.add(mesh);

        // Subtle bobbing animation
        group.userData.animate = (t) => {
            mesh.rotation.y = t * 0.5;
            mesh.rotation.x = Math.sin(t) * 0.15;
        };
    }

    return group;
}

// Animation loop for nodes
(function animLoop() {
    requestAnimationFrame(animLoop);
    if (!G) return;
    const t = performance.now() * 0.001;
    const gd = G.graphData();
    if (!gd || !gd.nodes) return;
    gd.nodes.forEach(n => {
        if (n.__threeObj && n.__threeObj.userData.animate) {
            n.__threeObj.userData.animate(t + (n._animOffset || 0));
        }
    });
})();

/* ═══════════════════════════════════════════════════════════
   Tooltips
   ═══════════════════════════════════════════════════════════ */

function buildTooltip(n) {
    const title = esc(n.title || n.name || 'Node');
    if (n._isInsight) {
        return `<div class="graph-tooltip">
            <div class="tt-title">💡 ${title}</div>
            <div class="tt-sub">${n.severity?.toUpperCase() || 'INSIGHT'} • ${Math.round((n.confidence || 0) * 100)}% confidence</div>
        </div>`;
    }
    return `<div class="graph-tooltip">
        <div class="tt-title">${title}</div>
        <div class="tt-sub">${(n.source || '').replace('_', ' ')} • ${(n.category || '').replace('_', ' ')}</div>
    </div>`;
}

/* ═══════════════════════════════════════════════════════════
   Click → Detail Panel
   ═══════════════════════════════════════════════════════════ */

function onClickNode(n) {
    // Fly camera
    const dist = 80;
    const ratio = 1 + dist / Math.hypot(n.x || 1, n.y || 1, n.z || 1);
    G.cameraPosition(
        { x: n.x * ratio, y: n.y * ratio, z: n.z * ratio },
        n, 1800
    );

    // Fill detail panel
    const p = document.getElementById('detail-panel');
    const b = document.getElementById('detail-body');
    const title = esc(n.title || n.name || 'Untitled');

    if (n._isInsight) {
        const sev = n.severity || 'info';
        const conf = Math.round((n.confidence || 0) * 100);
        const desc = esc(n.description || '');
        const type = n.insight_type || '';
        const doms = (Array.isArray(n.domains) ? n.domains : [])
            .map(d => `<span class="d-tag tag-${sev}">${esc(d)}</span>`).join(' ');

        b.innerHTML = `
            <div class="d-title">💡 ${title}</div>
            <div class="d-meta">
                <span class="d-tag tag-${sev}">${sev.toUpperCase()}</span>
                <span class="d-tag tag-insight">${type}</span>
                <span class="d-tag" style="background:rgba(255,255,255,.06);color:var(--text2)">Confidence ${conf}%</span>
            </div>
            ${doms ? '<div style="margin-bottom:14px"><b style="color:var(--text);font-size:.75rem">Domains:</b><br>' + doms + '</div>' : ''}
            <div class="d-content">${desc}</div>
        `;
    } else {
        const src = n.source || 'unknown';
        const cat = n.category || '';
        const time = timeAgo(n.collected_at);

        let body = '';
        if (n.metadata?.pipeline === 'certstream_keyword_monitor' && n.metadata.counts) {
            body = `<div style="margin-bottom:8px">${esc(n.content)}</div><ul>`;
            for (const [kw, count] of Object.entries(n.metadata.counts)) {
                body += `<li style="margin-bottom: 2px"><b>${esc(kw)}</b>: ${count} hits</li>`;
            }
            body += '</ul>';
        } else if (n.metadata?.pipeline === 'gdelt_extremes' && n.metadata.events) {
            body = `<div style="margin-bottom:8px">${esc(n.content)}</div><div style="max-height: 200px; overflow-y: auto;">`;
            n.metadata.events.forEach(ev => {
                body += `<div style="margin-bottom: 6px; padding: 6px; background: rgba(255,255,255,0.05); border-radius: 4px; font-size: 0.8rem">`;
                body += `<div><b>Actors:</b> ${esc(ev.actor1 || 'unknown')} - ${esc(ev.actor2 || 'unknown')}</div>`;
                if (ev.tone !== null) body += `<div><b>Tone:</b> ${ev.tone}</div>`;
                if (ev.goldstein !== null) body += `<div><b>Goldstein:</b> ${ev.goldstein}</div>`;
                if (ev.source_url) body += `<div style="margin-top:4px"><a class="d-link" href="${ev.source_url}" target="_blank">Source Link →</a></div>`;
                body += `</div>`;
            });
            body += '</div>';
        } else if (n.metadata?.pipeline === 'openphish_tld_aggregation' && n.metadata.top_tlds) {
            body = `<div style="margin-bottom:8px">${esc(n.content)}</div><div style="display: flex; gap: 6px; flex-wrap: wrap; margin-top: 8px">`;
            n.metadata.top_tlds.forEach(tld => {
                body += `<span class="d-tag tag-high">${esc(tld.tld)} (${tld.count})</span>`;
            });
            body += '</div>';
        } else {
            body = esc(typeof n.content === 'object' ? JSON.stringify(n.content, null, 2) : (n.content || ''));
        }

        b.innerHTML = `
            <div class="d-title">${title}</div>
            <div class="d-meta">
                <span class="d-tag tag-${src}">${src.replace('_', ' ').toUpperCase()}</span>
                <span class="d-tag" style="background:rgba(255,255,255,.06);color:var(--text2)">${cat.replace('_', ' ')}</span>
                <span style="font-size:.7rem;color:var(--text3)">${time}</span>
            </div>
            ${n.url ? `<a class="d-link" href="${n.url}" target="_blank">🔗 Open source link →</a>` : ''}
            <div class="d-content">${body || '<span class="muted">No content body available.</span>'}</div>
        `;
    }

    p.classList.add('open');
}

function closeDetail() {
    document.getElementById('detail-panel').classList.remove('open');
}

/* ═══════════════════════════════════════════════════════════
   Load Data → Build Graph
   ═══════════════════════════════════════════════════════════ */

async function loadData() {
    toast('Loading intelligence matrix…', 'info');

    const [dataRes, insightRes, statsRes] = await Promise.all([
        api('/api/data?limit=200'),
        api('/api/insights?limit=30'),
        api('/api/stats')
    ]);

    if (statsRes) refreshStats(statsRes);

    const nodes = [];
    const links = [];

    // ── Data items → nodes
    const items = dataRes?.items || [];
    items.forEach((d, i) => {
        d.id = 'D' + d.id;
        d._isInsight = false;
        d._animOffset = Math.random() * 100;
        nodes.push(d);
    });

    // ── Insights → big nodes + links to related data
    const insights = insightRes?.insights || [];
    insights.forEach((ins, i) => {
        ins.id = 'I' + ins.id;
        ins._isInsight = true;
        ins._animOffset = Math.random() * 100;
        nodes.push(ins);

        // Connect insight to data in matching domains
        const related = items.filter(d =>
            Array.isArray(ins.domains) && ins.domains.includes(d.category)
        );
        // Strong links to domain-matched items (up to 10)
        related.slice(0, 10).forEach(t => {
            links.push({
                source: ins.id, target: t.id,
                strong: true,
                color: sevHex(ins.severity)
            });
        });
        // Cross-domain weak links (3 random)
        shuffle(items).slice(0, 3).forEach(t => {
            if (t.id !== ins.id) {
                links.push({
                    source: ins.id, target: t.id,
                    strong: false,
                    color: 'rgba(255,255,255,0.08)'
                });
            }
        });
    });

    // ── Same-category data mesh (subtle background web)
    const cats = {};
    items.forEach(d => { (cats[d.category] = cats[d.category] || []).push(d); });
    Object.values(cats).forEach(arr => {
        for (let i = 0; i < Math.min(arr.length, 40); i++) {
            const a = arr[Math.floor(Math.random() * arr.length)];
            const b = arr[Math.floor(Math.random() * arr.length)];
            if (a !== b) {
                links.push({ source: a.id, target: b.id, strong: false, color: 'rgba(255,255,255,0.04)' });
            }
        }
    });

    G.graphData({ nodes, links });

    num('stat-data', items.length);
    num('stat-insights', insights.length);
    num('stat-links', links.length);

    toast(`Loaded ${items.length} data nodes + ${insights.length} insight nodes`, 'success');
}

function reloadGraph() { loadData(); }
function recenter() { G.zoomToFit(1200, 80); }

async function refreshStats(s) {
    if (!s) s = await api('/api/stats');
    if (!s) return;
    num('stat-alerts', s.active_alerts || 0);
    const llmDot = document.getElementById('llm-dot');
    const llmText = document.getElementById('llm-text');
    const on = s.llm_status === 'connected';
    llmDot.className = `dot ${on ? 'online' : 'offline'}`;
    llmText.textContent = on ? 'LLM Online' : 'LLM Offline';
}

/* ═══════════════════════════════════════════════════════════
   Actions
   ═══════════════════════════════════════════════════════════ */

async function doCollect() {
    const b = document.getElementById('btn-collect');
    b.disabled = true; b.textContent = '⏳ Collecting…';
    toast('Running data collection sweeps…', 'info');
    const r = await api('/api/collect/now', { method: 'POST' });
    if (r) {
        const n = Object.values(r.results || {}).reduce((s, v) => s + (typeof v === 'number' ? v : 0), 0);
        toast(`Collected ${n} new items`, 'success');
        await loadData();
    } else { toast('Collection error', 'error'); }
    b.disabled = false; b.textContent = '⚡ Collect Data';
}

async function doAnalyze() {
    const b = document.getElementById('btn-analyze');
    b.disabled = true; b.textContent = '⏳ Analyzing…';
    toast('Running pattern analysis…', 'info');
    const r = await api('/api/analyze/now', { method: 'POST' });
    if (r?.results) {
        toast(`Found ${r.results.analytics_insights || 0} patterns, ${r.results.alerts_generated || 0} alerts`, 'success');
        await loadData();
    } else { toast('Analysis error', 'error'); }
    b.disabled = false; b.textContent = '🧠 Find Patterns';
}

/* ═══════════════════════════════════════════════════════════
   WebSocket
   ═══════════════════════════════════════════════════════════ */

function connectWS() {
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    try {
        ws = new WebSocket(`${proto}//${location.host}/ws/live`);
        ws.onopen = () => {
            setWS(true);
            if (wsTimer) { clearInterval(wsTimer); wsTimer = null; }
        };
        ws.onmessage = e => {
            try {
                const m = JSON.parse(e.data);
                if (m.type === 'collection_complete' || m.type === 'analysis_complete') {
                    toast(m.type === 'collection_complete' ? 'Collection finished!' : 'Analysis complete!', 'success');
                    loadData();
                }
            } catch (_) { }
        };
        ws.onclose = () => { setWS(false); if (!wsTimer) wsTimer = setInterval(() => { if (!ws || ws.readyState === 3) connectWS(); }, 5000); };
        ws.onerror = () => setWS(false);
    } catch (_) { setWS(false); }
}

function setWS(on) {
    document.getElementById('ws-dot').className = `dot ${on ? 'online' : 'offline'}`;
    document.getElementById('ws-text').textContent = on ? 'Live' : 'Disconnected';
}

/* ═══════════════════════════════════════════════════════════
   Utils
   ═══════════════════════════════════════════════════════════ */

function toast(msg, type = 'info') {
    const c = document.getElementById('toasts');
    const d = document.createElement('div');
    d.className = `toast ${type}`;
    const icons = { success: '✓', error: '✗', info: 'ℹ' };
    d.innerHTML = `<b>${icons[type] || 'ℹ'}</b> ${esc(msg)}`;
    c.appendChild(d);
    setTimeout(() => { d.style.opacity = '0'; d.style.transform = 'translateX(30px)'; d.style.transition = '.3s'; setTimeout(() => d.remove(), 300); }, 4000);
}

function esc(t) { const d = document.createElement('div'); d.textContent = t; return d.innerHTML; }

function timeAgo(s) {
    if (!s) return '';
    try {
        const ms = Date.now() - new Date(s).getTime();
        const m = Math.floor(ms / 60000), h = Math.floor(ms / 3600000), d = Math.floor(ms / 86400000);
        if (m < 1) return 'just now'; if (m < 60) return m + 'm ago'; if (h < 24) return h + 'h ago'; if (d < 7) return d + 'd ago';
        return new Date(s).toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
    } catch (_) { return ''; }
}

function num(id, target) {
    const el = document.getElementById(id);
    if (!el) return;
    const cur = parseInt(el.textContent) || 0;
    if (cur === target) return;
    const diff = target - cur, steps = Math.min(Math.abs(diff), 25), step = diff / steps;
    let i = 0;
    const iv = setInterval(() => {
        i++;
        el.textContent = i >= steps ? target.toLocaleString() : Math.round(cur + step * i).toLocaleString();
        if (i >= steps) clearInterval(iv);
    }, 25);
}

function sevHex(s) {
    return { critical: 'rgba(239,68,68,0.5)', high: 'rgba(245,158,11,0.5)', medium: 'rgba(0,212,255,0.5)', low: 'rgba(168,85,247,0.5)' }[s] || 'rgba(144,144,168,0.3)';
}

function shuffle(a) { const b = [...a]; for (let i = b.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1));[b[i], b[j]] = [b[j], b[i]]; } return b; }
