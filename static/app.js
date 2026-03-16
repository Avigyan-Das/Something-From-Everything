/**
 * INTELLIGENCE NEXUS - Core Dashboard Engine
 * Version 2.5.1 | Performance Optimized
 */

let G = null;
let ws = null;
let wsTimer = null;
const API = "";

const graphState = {
    items: new Map(),
    insights: new Map(),
    connections: new Map(),
    offset: 0,
    hasMore: false,
    loading: false,
    limits: {
        default: 300,
        max: 2500,
        effective: 300,
    },
    tab: "visual",
    techData: [],
};

// Theme-aligned Colors
const THEME = {
    cyan: "#00f3ff",
    purple: "#7000ff",
    crimson: "#ff0055",
    amber: "#ffaa00",
    green: "#00ff9d",
    blue: "#0077ff",
    pink: "#ec4899",
    white: "#f0f0f5",
    muted: "#55556a",
};

const SEV_COLORS = {
    critical: 0xff0055,
    high: 0xffaa00,
    medium: 0x00f3ff,
    low: 0x7000ff,
    info: 0x55556a,
};

// ─── 3D Asset Cache (Performance Optimization) ─────────────
const GEO_CACHE = {
    rss: new THREE.SphereGeometry(3, 16, 16),
    reddit: new THREE.BoxGeometry(4, 4, 4),
    hackernews: new THREE.TorusGeometry(3, 0.8, 8, 16),
    finance: new THREE.OctahedronGeometry(3.5),
    weather: new THREE.IcosahedronGeometry(3.5),
    scraper: new THREE.CylinderGeometry(0, 3, 6, 4),
    insight: new THREE.SphereGeometry(10, 24, 24),
    shield: new THREE.TorusGeometry(15, 0.4, 8, 40),
};

const MAT_CACHE = new Map();
function getMaterial(color, wireframe = false, emissive = 0) {
    const key = `${color}_${wireframe}_${emissive}`;
    if (MAT_CACHE.has(key)) return MAT_CACHE.get(key);
    
    const mat = wireframe 
        ? new THREE.MeshBasicMaterial({ color, wireframe: true, transparent: true, opacity: 0.1 })
        : new THREE.MeshPhongMaterial({ 
            color, 
            transparent: true, 
            opacity: 0.85, 
            emissive: color, 
            emissiveIntensity: emissive 
        });
    
    MAT_CACHE.set(key, mat);
    return mat;
}

const SRC_MAP = {
    rss: { color: 0x00f3ff, geo: GEO_CACHE.rss },
    reddit: { color: 0xec4899, geo: GEO_CACHE.reddit },
    hackernews: { color: 0xffaa00, geo: GEO_CACHE.hackernews },
    finance_api: { color: 0x00ff9d, geo: GEO_CACHE.finance },
    weather_api: { color: 0x7000ff, geo: GEO_CACHE.weather },
    web_scraper: { color: 0xff0055, geo: GEO_CACHE.scraper },
};

// ─── Initialization ──────────────────────────────────────────

document.addEventListener("DOMContentLoaded", () => {
    initNexus();
});

async function initNexus() {
    buildGraph();
    connectWS();
    bindFilterControls();
    refreshStats();
    setInterval(() => refreshStats(), 60000);
}

async function api(path, opts = {}) {
    try {
        const r = await fetch(API + path, {
            headers: { "Content-Type": "application/json" },
            ...opts,
        });
        if (!r.ok) throw new Error(r.status);
        return await r.json();
    } catch (e) {
        console.warn("Nexus API Error:", path, e);
        return null;
    }
}

function buildGraph() {
    const el = document.getElementById("3d-graph");

    G = ForceGraph3D()(el)
        .backgroundColor("rgba(0,0,0,0)")
        .showNavInfo(false)
        .nodeThreeObject((n) => makeNode(n))
        .nodeThreeObjectExtend(false)
        .nodeLabel((n) => buildTooltip(n))
        .onNodeClick((n) => onClickNode(n))
        .linkWidth((l) => (l.strong ? 1.2 : 0.3))
        .linkOpacity(0.2)
        .linkColor((l) => l.color || "rgba(255,255,255,0.05)")
        .linkDirectionalParticles((l) => (l.strong ? 2 : 0))
        .linkDirectionalParticleWidth(1.2)
        .linkDirectionalParticleSpeed(0.01)
        .linkDirectionalParticleColor(() => THEME.cyan)
        .width(window.innerWidth)
        .height(window.innerHeight);

    G.d3Force("charge").strength(-120);
    G.d3Force("link").distance((l) => (l.strong ? 80 : 160));

    // Starfield (Static Buffer)
    const starGeo = new THREE.BufferGeometry();
    const verts = [];
    for (let i = 0; i < 3000; i++) {
        verts.push((Math.random() - 0.5) * 5000, (Math.random() - 0.5) * 5000, (Math.random() - 0.5) * 5000);
    }
    starGeo.setAttribute("position", new THREE.Float32BufferAttribute(verts, 3));
    const starMat = new THREE.PointsMaterial({ color: 0x333344, size: 1.5, transparent: true, opacity: 0.5 });
    G.scene().add(new THREE.Points(starGeo, starMat));

    G.scene().add(new THREE.AmbientLight(0xffffff, 0.9));
    
    window.addEventListener("resize", () => {
        G.width(window.innerWidth);
        G.height(window.innerHeight);
    });
}

function makeNode(n) {
    const group = new THREE.Group();

    if (n._isInsight) {
        const c = SEV_COLORS[n.severity] || SEV_COLORS.info;
        const core = new THREE.Mesh(GEO_CACHE.insight, getMaterial(c, false, 0.4));
        const shield = new THREE.Mesh(GEO_CACHE.shield, getMaterial(c, false, 0.1));
        shield.rotation.x = Math.PI / 2;
        group.add(core);
        group.add(shield);

        group.userData.animate = (t) => {
            shield.rotation.z = t * 0.5;
            core.scale.setScalar(1 + Math.sin(t * 2) * 0.05);
        };
    } else {
        const shape = SRC_MAP[n.source] || SRC_MAP.rss;
        const mesh = new THREE.Mesh(shape.geo, getMaterial(shape.color));
        const wire = new THREE.Mesh(shape.geo, getMaterial(0xffffff, true));
        group.add(mesh);
        group.add(wire);

        group.userData.animate = (t) => {
            mesh.rotation.y = t * 0.4;
            wire.rotation.y = t * 0.4;
        };
    }

    return group;
}

(function animLoop() {
    requestAnimationFrame(animLoop);
    if (!G || graphState.tab !== "visual") return;
    const t = performance.now() * 0.001;
    const gd = G.graphData();
    if (gd && gd.nodes) {
        // Only animate the first 500 nodes for performance if the graph is huge
        const limit = Math.min(gd.nodes.length, 600);
        for(let i=0; i<limit; i++) {
            const n = gd.nodes[i];
            if (n.__threeObj && n.__threeObj.userData.animate) {
                n.__threeObj.userData.animate(t + (n._animOffset || 0));
            }
        }
    }
})();

function buildTooltip(n) {
    const title = esc(n.title || n.name || "UNIDENTIFIED NODE");
    if (n._isInsight) {
        return `<div class="graph-tooltip">
            <div class="tt-title">INSIGHT: ${title}</div>
            <div class="tt-sub">${(n.severity || "info").toUpperCase()} • ${Math.round((n.confidence || 0) * 100)}% CONFIDENCE</div>
        </div>`;
    }
    return `<div class="graph-tooltip">
        <div class="tt-title">${title}</div>
        <div class="tt-sub">${(n.source || "stream").toUpperCase()} • ${(n.category || "data").toUpperCase()}</div>
    </div>`;
}

// ─── Data & Filters ──────────────────────────────────────────

function bindFilterControls() {
    const limitInput = document.getElementById("filter-limit");
    if (limitInput) {
        limitInput.addEventListener("change", () => {
            limitInput.value = String(clampLimit(Number(limitInput.value)));
        });
    }
}

function clampLimit(limit) {
    const val = Number.isFinite(limit) ? limit : graphState.limits.default;
    return Math.max(1, Math.min(Math.floor(val), graphState.limits.max));
}

function getFilters() {
    return {
        source: document.getElementById("filter-source")?.value || "",
        category: document.getElementById("filter-category")?.value || "",
        timeframe: document.getElementById("filter-timeframe")?.value || "all",
        start_time: getTimeStartIso(document.getElementById("filter-timeframe")?.value || "all"),
        insights_only: document.getElementById("filter-insights-only")?.checked || false,
        random: document.getElementById("filter-random")?.checked || false,
        limit: clampLimit(Number(document.getElementById("filter-limit")?.value || graphState.limits.default)),
    };
}

function getTimeStartIso(timeframe) {
    if (!timeframe || timeframe === "all") return null;
    const windows = { "1h": 3600, "6h": 21600, "24h": 86400, "7d": 604800 };
    const seconds = windows[timeframe];
    return seconds ? new Date(Date.now() - seconds * 1000).toISOString() : null;
}

async function loadData({ append }) {
    if (graphState.loading) return;
    graphState.loading = true;

    const filters = getFilters();
    const offset = append ? graphState.offset : 0;
    
    const btn = document.getElementById("btn-load-more");
    if (btn) { btn.disabled = true; btn.textContent = "PROCESSING..."; }
    toast(append ? "EXPANDING MATRIX..." : "SYNCHRONIZING NEXUS...", "info");

    const q = new URLSearchParams({
        limit: String(filters.limit),
        offset: String(offset),
        insights_only: String(filters.insights_only),
    });
    if (filters.random) q.set("random", "true");
    if (filters.source) q.set("source", filters.source);
    if (filters.category) q.set("category", filters.category);
    if (filters.start_time) q.set("start_time", filters.start_time);

    const res = await api("/api/graph-data?" + q.toString());
    const stats = await api("/api/stats");
    if (stats) refreshStats(stats);

    if (!res) {
        graphState.loading = false;
        if (btn) { btn.disabled = false; btn.textContent = "RETRY CONNECTION"; }
        toast("DATA SYNC FAILED", "error");
        return;
    }

    if (!append) {
        graphState.items.clear();
        graphState.insights.clear();
        graphState.connections.clear();
    }

    (res.items || []).forEach(i => graphState.items.set(String(i.id), i));
    (res.insights || []).forEach(i => graphState.insights.set(String(i.id), i));
    
    Object.entries(res.connections || {}).forEach(([insightId, rawIds]) => {
        const bucket = graphState.connections.get(insightId) || new Set();
        rawIds.forEach(id => bucket.add(String(id)));
        graphState.connections.set(insightId, bucket);
    });

    graphState.offset = Number(res.next_offset || 0);
    graphState.hasMore = Boolean(res.has_more);
    
    updateFilterOptions(res.available_sources, res.available_categories);
    rehydrateGraphNodes();

    if (document.getElementById("filter-meta")) {
        document.getElementById("filter-meta").textContent = `NODES: ${graphState.items.size} | OFFSET: ${graphState.offset}`;
    }

    if (btn) {
        btn.disabled = !graphState.hasMore;
        btn.textContent = graphState.hasMore ? "EXPAND MATRIX" : "MATRIX COMPLETE";
    }
    
    graphState.loading = false;
    toast(`NEXUS SYNCED: ${graphState.items.size} NODES`, "success");
}

function updateFilterOptions(sources, categories) {
    const refill = (id, vals) => {
        const el = document.getElementById(id);
        if (!el || !vals) return;
        const current = el.value;
        el.innerHTML = `<option value="">ALL ${id.includes("source") ? "STREAMS" : "CATEGORIES"}</option>`;
        vals.forEach(v => {
            const opt = document.createElement("option");
            opt.value = v; opt.textContent = v;
            el.appendChild(opt);
        });
        el.value = current;
    };
    refill("filter-source", sources);
    refill("filter-category", categories);
}

function rehydrateGraphNodes() {
    const nodes = [];
    const links = [];

    const dataItems = Array.from(graphState.items.values());
    dataItems.forEach(item => {
        nodes.push({ ...item, id: "D" + item.id, _isInsight: false, _animOffset: Math.random() * 100 });
    });

    const insights = Array.from(graphState.insights.values());
    insights.forEach(insight => {
        nodes.push({ ...insight, id: "I" + insight.id, _isInsight: true, _animOffset: Math.random() * 100 });
    });

    graphState.connections.forEach((dataIdSet, rawInsightId) => {
        const insight = graphState.insights.get(rawInsightId);
        if (!insight) return;
        dataIdSet.forEach(rawDataId => {
            if (graphState.items.has(rawDataId)) {
                links.push({
                    source: "I" + rawInsightId,
                    target: "D" + rawDataId,
                    strong: true,
                    color: sevColor(insight.severity, 0.4),
                });
            }
        });
    });

    // structure sub-links
    const cats = {};
    dataItems.forEach(i => { (cats[i.category] = cats[i.category] || []).push(i); });
    Object.values(cats).forEach(arr => {
        const linkLimit = Math.min(arr.length, 15);
        for (let i = 0; i < linkLimit; i++) {
            const a = arr[Math.floor(Math.random() * arr.length)];
            const b = arr[Math.floor(Math.random() * arr.length)];
            if (a.id !== b.id) links.push({ source: "D" + a.id, target: "D" + b.id, strong: false });
        }
    });

    G.graphData({ nodes, links });
    animateValue("stat-data", dataItems.length);
    animateValue("stat-insights", insights.length);
    animateValue("stat-links", links.length);
}

// ─── Interaction ─────────────────────────────────────────────

function onClickNode(n) {
    const dist = 120;
    const ratio = 1 + dist / Math.hypot(n.x || 1, n.y || 1, n.z || 1);
    G.cameraPosition({ x: n.x * ratio, y: n.y * ratio, z: n.z * ratio }, n, 1000);

    const panel = document.getElementById("detail-panel");
    const body = document.getElementById("detail-body");
    const title = esc(n.title || n.name || "UNIDENTIFIED NODE");

    if (n._isInsight) {
        const sev = n.severity || "info";
        const tags = (n.domains || []).map(d => `<span class="d-tag tag-cyan">${esc(d)}</span>`).join("");
        body.innerHTML = `
            <div class="d-title">${title}</div>
            <div class="d-meta">
                <span class="d-tag tag-${sev === 'critical' ? 'crimson' : sev === 'high' ? 'amber' : 'purple'}">${sev.toUpperCase()}</span>
                <span class="d-tag">CONFIDENCE ${Math.round((n.confidence || 0) * 100)}%</span>
            </div>
            <div style="margin-bottom:20px">${tags}</div>
            <div class="d-content">${esc(n.description || "")}</div>
        `;
    } else {
        body.innerHTML = `
            <div class="d-title">${title}</div>
            <div class="d-meta">
                <span class="d-tag tag-cyan">${(n.source || "STREAM").toUpperCase()}</span>
                <span class="d-tag">${(n.category || "GENERAL").toUpperCase()}</span>
                <span class="d-tag">${timeAgo(n.collected_at)}</span>
            </div>
            ${n.url ? `<a href="${n.url}" target="_blank" class="d-link">OPEN SOURCE INTELLIGENCE ↗</a>` : ""}
            <div class="d-content" style="margin-top:20px">${esc(String(n.content || ""))}</div>
        `;
    }
    panel.classList.add("open");
}

// ─── Utils ───────────────────────────────────────────────────

function esc(t) {
    const d = document.createElement("div");
    d.textContent = t;
    return d.innerHTML;
}

function timeAgo(s) {
    if (!s) return "";
    const ms = Date.now() - new Date(s).getTime();
    const m = Math.floor(ms / 60000);
    if (m < 1) return "JUST NOW";
    if (m < 60) return `${m}M AGO`;
    const h = Math.floor(ms / 3600000);
    if (h < 24) return `${h}H AGO`;
    return new Date(s).toLocaleDateString();
}

function sevColor(s, alpha = 1) {
    const colors = { critical: `rgba(255,0,85,${alpha})`, high: `rgba(255,170,0,${alpha})`, medium: `rgba(0,243,255,${alpha})`, low: `rgba(112,0,255,${alpha})` };
    return colors[s] || `rgba(160,160,184,${alpha})`;
}

function animateValue(id, target) {
    const el = document.getElementById(id);
    if (!el) return;
    const current = parseInt(el.textContent) || 0;
    if (current === target) return;
    let start = null;
    function step(t) {
        if (!start) start = t;
        const progress = Math.min((t - start) / 800, 1);
        el.textContent = Math.floor(progress * (target - current) + current).toLocaleString();
        if (progress < 1) requestAnimationFrame(step);
    }
    requestAnimationFrame(step);
}

function toast(msg, type = "info") {
    const container = document.getElementById("toasts");
    const d = document.createElement("div");
    d.className = `toast ${type}`;
    d.innerHTML = `<b>${type.toUpperCase()}</b> ${esc(msg)}`;
    container.appendChild(d);
    setTimeout(() => { d.style.opacity = "0"; setTimeout(() => d.remove(), 500); }, 4000);
}

// ─── Actions & Navigation ────────────────────────────────────

async function doAnalyze() {
    const btn = document.getElementById("btn-analyze");
    btn.disabled = true;
    btn.querySelector(".btn-label").textContent = "SYNTHESIZING...";
    const r = await api("/api/analyze/now", { method: "POST", body: JSON.stringify(getFilters()) });
    if (r && r.results) {
        toast(`SYNTHESIZED ${r.results.analytics_insights} PATTERNS`, "success");
        loadData({ append: false });
    }
    btn.disabled = false;
    btn.querySelector(".btn-label").textContent = "SYNTHESIZE PATTERNS";
}

async function doCollect() {
    const btn = document.getElementById("btn-collect");
    btn.disabled = true; btn.textContent = "HARVESTING...";
    const r = await api("/api/collect/now", { method: "POST" });
    if (r) {
        toast("HARVEST COMPLETE", "success");
        loadData({ append: false });
    }
    btn.disabled = false; btn.textContent = "⚡ TRIGGER HARVEST";
}

function switchTheme(id) {
    if (graphState.tab === id) return;
    graphState.tab = id;
    document.querySelectorAll(".tab-btn").forEach(b => b.classList.toggle("active", b.dataset.tab === id));
    document.querySelectorAll(".tab-content").forEach(c => c.classList.toggle("active", c.id === `tab-${id}`));
    if (id === "visual") { if (G) G.resumeAnimation(); } 
    else { if (G) G.pauseAnimation(); loadTableData(); }
}

async function loadTableData() {
    const res = await api("/api/data?limit=1000");
    if (res && res.items) {
        graphState.techData = res.items;
        filterTechTable();
    }
}

function filterTechTable() {
    const term = (document.getElementById("tech-search")?.value || "").toLowerCase();
    const filtered = graphState.techData.filter(i => !term || String(i.content).toLowerCase().includes(term));
    document.getElementById("tech-meta").textContent = `${filtered.length} RECORDS`;
    const body = document.getElementById("tech-table-body");
    body.innerHTML = filtered.map(i => `
        <tr>
            <td class="col-time">${timeAgo(i.collected_at)}</td>
            <td class="col-source">${esc(i.source)}</td>
            <td class="col-cat">${esc(i.category)}</td>
            <td>${esc(String(i.content).substring(0, 150))}...</td>
            <td class="col-link">${i.url ? `<a href="${i.url}" target="_blank" style="color:var(--accent-cyan)">↗</a>` : '-'}</td>
        </tr>
    `).join("");
}

function connectWS() {
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    ws = new WebSocket(`${proto}//${location.host}/ws/live`);
    ws.onopen = () => updateWSStatus(true);
    ws.onclose = () => { updateWSStatus(false); setTimeout(connectWS, 5000); };
    ws.onmessage = (e) => {
        const m = JSON.parse(e.data);
        if (m.type === "analysis_complete" || m.type === "collection_complete") {
            toast(m.type.replace("_", " ").toUpperCase(), "success");
            loadData({ append: false });
        }
    };
}

function updateWSStatus(on) {
    const dot = document.getElementById("ws-dot");
    const text = document.getElementById("ws-text");
    if(dot && text) {
        dot.className = `status-dot ${on ? 'online' : 'offline'}`;
        text.textContent = on ? 'NEXUS LIVE' : 'DISCONNECTED';
    }
}

async function refreshStats(s) {
    if (!s) s = await api("/api/stats");
    if (!s) return;
    animateValue("stat-alerts", s.active_alerts || 0);
    const on = s.llm_status === "connected";
    if(document.getElementById("llm-dot")) {
        document.getElementById("llm-dot").className = `status-dot ${on ? 'online' : 'offline'}`;
        document.getElementById("llm-text").textContent = on ? 'LLM ACTIVE' : 'LLM OFFLINE';
    }
}

// Global Exports
window.switchTheme = switchTheme;
window.applyFilters = () => loadData({ append: false });
window.loadMore = () => loadData({ append: true });
window.doAnalyze = doAnalyze;
window.doCollect = doCollect;
window.reloadGraph = () => loadData({ append: false });
window.recenter = () => G.zoomToFit(1000, 100);
window.closeDetail = () => document.getElementById("detail-panel").classList.remove("open");
window.filterTechTable = filterTechTable;
window.loadTableData = loadTableData;
