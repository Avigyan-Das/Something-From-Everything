/**
 * Something from Everything - 3D Intelligence Dashboard
 * Full-screen interactive 3D force-directed graph.
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
    techData: [], // raw data for Technical Console table
};

document.addEventListener("DOMContentLoaded", () => {
    buildGraph();
    connectWS();
    bindFilterControls();
    loadData({ append: false });
    setInterval(() => refreshStats(), 60000);
});

async function api(path, opts = {}) {
    try {
        const r = await fetch(API + path, {
            headers: { "Content-Type": "application/json" },
            ...opts,
        });
        if (!r.ok) throw new Error(r.status);
        return await r.json();
    } catch (e) {
        console.warn("api", path, e);
        return null;
    }
}

function buildGraph() {
    const el = document.getElementById("3d-graph");

    G = ForceGraph3D()(el)
        .backgroundColor("#060610")
        .showNavInfo(false)
        .nodeThreeObject((n) => makeNode(n))
        .nodeThreeObjectExtend(false)
        .nodeLabel((n) => buildTooltip(n))
        .onNodeClick((n) => onClickNode(n))
        .linkWidth((l) => (l.strong ? 1.8 : 0.4))
        .linkOpacity(0.6)
        .linkColor((l) => l.color || "rgba(255,255,255,0.15)")
        .linkDirectionalParticles((l) => (l.strong ? 3 : 0))
        .linkDirectionalParticleWidth(1.5)
        .linkDirectionalParticleSpeed(0.006)
        .linkDirectionalParticleColor(() => "#00d4ff")
        .width(window.innerWidth)
        .height(window.innerHeight);

    G.d3Force("charge").strength(-80);
    G.d3Force("link").distance((l) => (l.strong ? 60 : 120));

    const starGeo = new THREE.BufferGeometry();
    const verts = [];
    for (let i = 0; i < 3000; i++) {
        verts.push(
            (Math.random() - 0.5) * 4000,
            (Math.random() - 0.5) * 4000,
            (Math.random() - 0.5) * 4000
        );
    }
    starGeo.setAttribute("position", new THREE.Float32BufferAttribute(verts, 3));
    const starMat = new THREE.PointsMaterial({
        color: 0x555577,
        size: 1.5,
        transparent: true,
        opacity: 0.7,
    });
    G.scene().add(new THREE.Points(starGeo, starMat));

    G.scene().add(new THREE.AmbientLight(0xcccccc, 1.2));
    G.scene().add(new THREE.DirectionalLight(0xffffff, 0.8));

    window.addEventListener("resize", () => {
        G.width(window.innerWidth);
        G.height(window.innerHeight);
    });
}

const SEV_COLORS = {
    critical: 0xef4444,
    high: 0xf59e0b,
    medium: 0x00d4ff,
    low: 0xa855f7,
    info: 0x9090a8,
};

const SRC_MAP = {
    rss: { color: 0x00d4ff, make: () => new THREE.SphereGeometry(3.5, 24, 24) },
    reddit: { color: 0xec4899, make: () => new THREE.BoxGeometry(5, 5, 5) },
    hackernews: { color: 0xf59e0b, make: () => new THREE.TorusGeometry(3.5, 1.2, 8, 20) },
    finance_api: { color: 0x10b981, make: () => new THREE.ConeGeometry(3.5, 7, 6) },
    weather_api: { color: 0xa855f7, make: () => new THREE.IcosahedronGeometry(3.5) },
    web_scraper: { color: 0xef4444, make: () => new THREE.OctahedronGeometry(3.5) },
};

function makeNode(n) {
    const group = new THREE.Group();

    if (n._isInsight) {
        const c = SEV_COLORS[n.severity] || SEV_COLORS.info;

        const core = new THREE.Mesh(
            new THREE.SphereGeometry(9, 32, 32),
            new THREE.MeshPhongMaterial({
                color: c,
                emissive: c,
                emissiveIntensity: 0.55,
                transparent: true,
                opacity: 0.92,
            })
        );
        group.add(core);

        const halo = new THREE.Mesh(
            new THREE.SphereGeometry(14, 32, 32),
            new THREE.MeshBasicMaterial({
                color: c,
                transparent: true,
                opacity: 0.12,
                side: THREE.BackSide,
            })
        );
        group.add(halo);

        const ring = new THREE.Mesh(
            new THREE.TorusGeometry(16, 0.4, 16, 60),
            new THREE.MeshBasicMaterial({ color: c, transparent: true, opacity: 0.25 })
        );
        ring.rotation.x = Math.PI / 2;
        group.add(ring);

        group.userData.animate = (t) => {
            ring.rotation.z = t * 0.3;
            halo.scale.setScalar(1 + Math.sin(t * 2) * 0.06);
        };
    } else {
        let shape;
        if (n.metadata && n.metadata.pipeline === "certstream_keyword_monitor") {
            shape = {
                color: 0x39ff14,
                make: () => new THREE.CylinderGeometry(2, 2, 8, 16),
            };
        } else if (n.metadata && n.metadata.pipeline === "gdelt_extremes") {
            shape = {
                color: 0xff4500,
                make: () => new THREE.SphereGeometry(4.5, 16, 16),
            };
        } else if (n.metadata && n.metadata.pipeline === "openphish_tld_aggregation") {
            shape = {
                color: 0x8a2be2,
                make: () => new THREE.DodecahedronGeometry(3.5),
            };
        } else {
            shape = SRC_MAP[n.source] || SRC_MAP.rss;
        }

        const mesh = new THREE.Mesh(
            shape.make(),
            new THREE.MeshLambertMaterial({
                color: shape.color,
                transparent: true,
                opacity: 0.85,
            })
        );
        group.add(mesh);

        group.userData.animate = (t) => {
            mesh.rotation.y = t * 0.5;
            mesh.rotation.x = Math.sin(t) * 0.15;
        };
    }

    return group;
}

(function animLoop() {
    requestAnimationFrame(animLoop);
    if (!G || graphState.tab !== "visual") return;

    const t = performance.now() * 0.001;
    const gd = G.graphData();
    if (!gd || !gd.nodes) return;

    gd.nodes.forEach((n) => {
        if (n.__threeObj && n.__threeObj.userData.animate) {
            n.__threeObj.userData.animate(t + (n._animOffset || 0));
        }
    });
})();

function bindFilterControls() {
    const limitInput = document.getElementById("filter-limit");
    if (limitInput) {
        limitInput.addEventListener("change", () => {
            limitInput.value = String(clampLimit(Number(limitInput.value || graphState.limits.default)));
        });
    }
}

function clampLimit(limit) {
    const val = Number.isFinite(limit) ? limit : graphState.limits.default;
    return Math.max(1, Math.min(Math.floor(val), graphState.limits.max));
}

function getTimeStartIso(timeframe) {
    if (!timeframe || timeframe === "all") return null;
    const now = Date.now();
    const map = {
        "1h": 60 * 60 * 1000,
        "6h": 6 * 60 * 60 * 1000,
        "24h": 24 * 60 * 60 * 1000,
        "7d": 7 * 24 * 60 * 60 * 1000,
        "30d": 30 * 24 * 60 * 60 * 1000,
    };
    const windowMs = map[timeframe];
    if (!windowMs) return null;
    return new Date(now - windowMs).toISOString();
}

function getFilters() {
    const source = (document.getElementById("filter-source") || {}).value || "";
    const category = (document.getElementById("filter-category") || {}).value || "";
    const timeframe = (document.getElementById("filter-timeframe") || {}).value || "all";
    const insightsOnly = (document.getElementById("filter-insights-only") || {}).checked || false;
    const isRandom = (document.getElementById("filter-random") || {}).checked || false;
    const rawLimit = Number((document.getElementById("filter-limit") || {}).value || graphState.limits.default);
    const limit = clampLimit(rawLimit);

    return {
        source,
        category,
        timeframe,
        start_time: getTimeStartIso(timeframe),
        end_time: null,
        insights_only: insightsOnly,
        random: isRandom,
        limit,
    };
}

function buildGraphDataPath(filters, offset) {
    const q = new URLSearchParams();
    q.set("limit", String(filters.limit));
    q.set("offset", String(offset));
    q.set("insight_limit", "300");
    q.set("insights_only", String(filters.insights_only));
    if (filters.random) q.set("random", "true");
    if (filters.source) q.set("source", filters.source);
    if (filters.category) q.set("category", filters.category);
    if (filters.start_time) q.set("start_time", filters.start_time);
    if (filters.end_time) q.set("end_time", filters.end_time);
    return "/api/graph-data?" + q.toString();
}

function upsertFilterOptions(selectId, values) {
    const select = document.getElementById(selectId);
    if (!select || !Array.isArray(values)) return;

    const existing = new Set(Array.from(select.options).map((o) => o.value));
    values.forEach((v) => {
        if (!v || existing.has(v)) return;
        const opt = document.createElement("option");
        opt.value = v;
        opt.textContent = v;
        select.appendChild(opt);
    });
}

function mergeConnections(target, source) {
    Object.entries(source || {}).forEach(([insightId, rawIds]) => {
        if (!Array.isArray(rawIds) || !rawIds.length) return;
        const bucket = target.get(insightId) || new Set();
        rawIds.forEach((id) => {
            if (id) bucket.add(String(id));
        });
        target.set(insightId, bucket);
    });
}

function rehydrateGraphNodes() {
    const nodes = [];
    const links = [];

    const prefixedDataIdByRawId = new Map();
    const dataItems = Array.from(graphState.items.values());
    dataItems.forEach((item) => {
        const rawId = String(item.id);
        const prefixedId = "D" + rawId;
        prefixedDataIdByRawId.set(rawId, prefixedId);
        nodes.push({
            ...item,
            id: prefixedId,
            _isInsight: false,
            _animOffset: Math.random() * 100,
        });
    });

    const prefixedInsightIdByRawId = new Map();
    const insights = Array.from(graphState.insights.values());
    insights.forEach((insight) => {
        const rawId = String(insight.id);
        const prefixedId = "I" + rawId;
        prefixedInsightIdByRawId.set(rawId, prefixedId);
        nodes.push({
            ...insight,
            id: prefixedId,
            _isInsight: true,
            _animOffset: Math.random() * 100,
        });
    });

    graphState.connections.forEach((dataIdSet, rawInsightId) => {
        const sourceId = prefixedInsightIdByRawId.get(rawInsightId);
        if (!sourceId) return;

        const insight = graphState.insights.get(rawInsightId) || {};
        dataIdSet.forEach((rawDataId) => {
            const targetId = prefixedDataIdByRawId.get(rawDataId);
            if (!targetId) return;
            links.push({
                source: sourceId,
                target: targetId,
                strong: true,
                color: sevHex(insight.severity),
            });
        });
    });

    const categories = {};
    dataItems.forEach((item) => {
        const cat = item.category || "general";
        if (!categories[cat]) categories[cat] = [];
        categories[cat].push(item);
    });

    Object.values(categories).forEach((arr) => {
        for (let i = 0; i < Math.min(arr.length, 40); i++) {
            const a = arr[Math.floor(Math.random() * arr.length)];
            const b = arr[Math.floor(Math.random() * arr.length)];
            if (a.id !== b.id) {
                links.push({
                    source: prefixedDataIdByRawId.get(String(a.id)),
                    target: prefixedDataIdByRawId.get(String(b.id)),
                    strong: false,
                    color: "rgba(255,255,255,0.04)",
                });
            }
        }
    });

    G.graphData({ nodes, links });
    num("stat-data", dataItems.length);
    num("stat-insights", insights.length);
    num("stat-links", links.length);
}

async function loadData({ append }) {
    if (graphState.loading) return;
    graphState.loading = true;

    const filters = getFilters();
    const offset = append ? graphState.offset : 0;
    const path = buildGraphDataPath(filters, offset);

    setLoadMoreState(false, "Loading...");
    toast(append ? "Loading more graph nodes..." : "Loading intelligence matrix...", "info");

    const graphRes = await api(path);
    const statsRes = await api("/api/stats");
    if (statsRes) refreshStats(statsRes);

    if (!graphRes) {
        graphState.loading = false;
        setLoadMoreState(true, "Load More");
        toast("Failed to fetch graph data", "error");
        return;
    }

    graphState.limits.default = graphRes.fetch_limits?.default || graphState.limits.default;
    graphState.limits.max = graphRes.fetch_limits?.max || graphState.limits.max;
    graphState.limits.effective = graphRes.fetch_limits?.effective || filters.limit;

    const limitInput = document.getElementById("filter-limit");
    if (limitInput) {
        limitInput.max = String(graphState.limits.max);
        limitInput.value = String(clampLimit(Number(limitInput.value || graphState.limits.default)));
    }

    upsertFilterOptions("filter-source", graphRes.available_sources || []);
    upsertFilterOptions("filter-category", graphRes.available_categories || []);

    if (!append) {
        graphState.items.clear();
        graphState.insights.clear();
        graphState.connections.clear();
    }

    (graphRes.items || []).forEach((item) => {
        if (!item || !item.id) return;
        graphState.items.set(String(item.id), item);
    });

    (graphRes.insights || []).forEach((insight) => {
        if (!insight || !insight.id) return;
        graphState.insights.set(String(insight.id), insight);
    });

    mergeConnections(graphState.connections, graphRes.connections || {});

    graphState.offset = Number(graphRes.next_offset || 0);
    graphState.hasMore = Boolean(graphRes.has_more);

    const meta = document.getElementById("filter-meta");
    if (meta) {
        meta.textContent =
            "Loaded " +
            graphState.items.size.toLocaleString() +
            " nodes, offset " +
            graphState.offset.toLocaleString() +
            (graphState.hasMore ? " (more available)" : " (end)");
    }

    rehydrateGraphNodes();

    setLoadMoreState(graphState.hasMore, graphState.hasMore ? "Load More" : "No More Data");
    graphState.loading = false;

    toast(
        "Graph has " +
            graphState.items.size.toLocaleString() +
            " data nodes and " +
            graphState.insights.size.toLocaleString() +
            " insights",
        "success"
    );
}

function applyFilters() {
    graphState.offset = 0;
    loadData({ append: false });
}

function loadMore() {
    if (!graphState.hasMore) return;
    loadData({ append: true });
}

function setLoadMoreState(enabled, label) {
    const btn = document.getElementById("btn-load-more");
    if (!btn) return;
    btn.disabled = !enabled;
    btn.textContent = label;
}

function buildTooltip(n) {
    const title = esc(n.title || n.name || "Node");
    if (n._isInsight) {
        return `<div class="graph-tooltip">
            <div class="tt-title">Insight: ${title}</div>
            <div class="tt-sub">${(n.severity || "info").toUpperCase()} • ${Math.round((n.confidence || 0) * 100)}% confidence</div>
        </div>`;
    }
    return `<div class="graph-tooltip">
        <div class="tt-title">${title}</div>
        <div class="tt-sub">${(n.source || "").replace("_", " ")} • ${(n.category || "").replace("_", " ")}</div>
    </div>`;
}

function onClickNode(n) {
    const dist = 80;
    const ratio = 1 + dist / Math.hypot(n.x || 1, n.y || 1, n.z || 1);
    G.cameraPosition({ x: n.x * ratio, y: n.y * ratio, z: n.z * ratio }, n, 1800);

    const p = document.getElementById("detail-panel");
    const b = document.getElementById("detail-body");
    const title = esc(n.title || n.name || "Untitled");

    if (n._isInsight) {
        const sev = n.severity || "info";
        const conf = Math.round((n.confidence || 0) * 100);
        const desc = esc(n.description || "");
        const type = n.insight_type || "";
        const doms = (Array.isArray(n.domains) ? n.domains : [])
            .map((d) => `<span class="d-tag tag-${sev}">${esc(d)}</span>`)
            .join(" ");

        b.innerHTML = `
            <div class="d-title">Insight: ${title}</div>
            <div class="d-meta">
                <span class="d-tag tag-${sev}">${sev.toUpperCase()}</span>
                <span class="d-tag tag-insight">${type}</span>
                <span class="d-tag" style="background:rgba(255,255,255,.06);color:var(--text2)">Confidence ${conf}%</span>
            </div>
            ${doms ? '<div style="margin-bottom:14px"><b style="color:var(--text);font-size:.75rem">Domains:</b><br>' + doms + "</div>" : ""}
            <div class="d-content">${desc}</div>
        `;
    } else {
        const src = n.source || "unknown";
        const cat = n.category || "";
        const time = timeAgo(n.collected_at);

        let body = "";
        if (n.metadata && n.metadata.pipeline === "certstream_keyword_monitor" && n.metadata.counts) {
            body = `<div style="margin-bottom:8px">${esc(n.content)}</div><ul>`;
            Object.entries(n.metadata.counts).forEach(([kw, count]) => {
                body += `<li style="margin-bottom:2px"><b>${esc(kw)}</b>: ${count} hits</li>`;
            });
            body += "</ul>";
        } else if (n.metadata && n.metadata.pipeline === "gdelt_extremes" && n.metadata.events) {
            body = `<div style="margin-bottom:8px">${esc(n.content)}</div><div style="max-height:200px;overflow-y:auto;">`;
            n.metadata.events.forEach((ev) => {
                body += `<div style="margin-bottom:6px;padding:6px;background:rgba(255,255,255,0.05);border-radius:4px;font-size:0.8rem">`;
                body += `<div><b>Actors:</b> ${esc(ev.actor1 || "unknown")} - ${esc(ev.actor2 || "unknown")}</div>`;
                if (ev.tone !== null) body += `<div><b>Tone:</b> ${ev.tone}</div>`;
                if (ev.goldstein !== null) body += `<div><b>Goldstein:</b> ${ev.goldstein}</div>`;
                if (ev.source_url) {
                    body += `<div style="margin-top:4px"><a class="d-link" href="${ev.source_url}" target="_blank">Source Link -></a></div>`;
                }
                body += "</div>";
            });
            body += "</div>";
        } else if (n.metadata && n.metadata.pipeline === "openphish_tld_aggregation" && n.metadata.top_tlds) {
            body = `<div style="margin-bottom:8px">${esc(n.content)}</div><div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:8px">`;
            n.metadata.top_tlds.forEach((tld) => {
                body += `<span class="d-tag tag-high">${esc(tld.tld)} (${tld.count})</span>`;
            });
            body += "</div>";
        } else {
            body = esc(typeof n.content === "object" ? JSON.stringify(n.content, null, 2) : n.content || "");
        }

        b.innerHTML = `
            <div class="d-title">${title}</div>
            <div class="d-meta">
                <span class="d-tag tag-${src}">${src.replace("_", " ").toUpperCase()}</span>
                <span class="d-tag" style="background:rgba(255,255,255,.06);color:var(--text2)">${cat.replace("_", " ")}</span>
                <span style="font-size:.7rem;color:var(--text3)">${time}</span>
            </div>
            ${n.url ? `<a class="d-link" href="${n.url}" target="_blank">Open source link -></a>` : ""}
            <div class="d-content">${body || '<span class="muted">No content body available.</span>'}</div>
        `;
    }

    p.classList.add("open");
}

function closeDetail() {
    document.getElementById("detail-panel").classList.remove("open");
}

function reloadGraph() {
    applyFilters();
}

function recenter() {
    G.zoomToFit(1200, 80);
}

async function refreshStats(s) {
    if (!s) s = await api("/api/stats");
    if (!s) return;
    num("stat-alerts", s.active_alerts || 0);
    const llmDot = document.getElementById("llm-dot");
    const llmText = document.getElementById("llm-text");
    const on = s.llm_status === "connected";
    llmDot.className = `dot ${on ? "online" : "offline"}`;
    llmText.textContent = on ? "LLM Online" : "LLM Offline";
}

async function doCollect() {
    const b = document.getElementById("btn-collect");
    b.disabled = true;
    b.textContent = "Collecting...";
    toast("Running data collection sweeps...", "info");

    const r = await api("/api/collect/now", { method: "POST" });
    if (r) {
        const n = Object.values(r.results || {}).reduce((sum, v) => sum + (typeof v === "number" ? v : 0), 0);
        toast(`Collected ${n} new items`, "success");
        await loadData({ append: false });
    } else {
        toast("Collection error", "error");
    }

    b.disabled = false;
    b.textContent = "Collect Data";
}

async function doAnalyze() {
    const b = document.getElementById("btn-analyze");
    b.disabled = true;
    b.textContent = "Analyzing...";
    
    // Grab current filters
    const filters = getFilters();
    
    toast("Running pattern analysis on filtered view...", "info");

    const r = await api("/api/analyze/now", { 
        method: "POST",
        body: JSON.stringify(filters)
    });
    
    if (r && r.results) {
        toast(`Found ${r.results.analytics_insights || 0} patterns, ${r.results.alerts_generated || 0} alerts`, "success");
        await loadData({ append: false });
    } else {
        toast("Analysis error", "error");
    }

    b.disabled = false;
    b.textContent = "Find Patterns";
}

function connectWS() {
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    try {
        ws = new WebSocket(`${proto}//${location.host}/ws/live`);
        ws.onopen = () => {
            setWS(true);
            if (wsTimer) {
                clearInterval(wsTimer);
                wsTimer = null;
            }
        };
        ws.onmessage = (e) => {
            try {
                const m = JSON.parse(e.data);
                if (m.type === "collection_complete" || m.type === "analysis_complete") {
                    toast(m.type === "collection_complete" ? "Collection finished" : "Analysis complete", "success");
                    loadData({ append: false });
                }
            } catch (_) {
                // Ignore malformed payloads.
            }
        };
        ws.onclose = () => {
            setWS(false);
            if (!wsTimer) {
                wsTimer = setInterval(() => {
                    if (!ws || ws.readyState === 3) connectWS();
                }, 5000);
            }
        };
        ws.onerror = () => setWS(false);
    } catch (_) {
        setWS(false);
    }
}

function setWS(on) {
    document.getElementById("ws-dot").className = `dot ${on ? "online" : "offline"}`;
    document.getElementById("ws-text").textContent = on ? "Live" : "Disconnected";
}

function toast(msg, type = "info") {
    const c = document.getElementById("toasts");
    const d = document.createElement("div");
    d.className = `toast ${type}`;
    const icons = { success: "OK", error: "ERR", info: "INFO" };
    d.innerHTML = `<b>${icons[type] || "INFO"}</b> ${esc(msg)}`;
    c.appendChild(d);

    setTimeout(() => {
        d.style.opacity = "0";
        d.style.transform = "translateX(30px)";
        d.style.transition = ".3s";
        setTimeout(() => d.remove(), 300);
    }, 4000);
}

function esc(t) {
    const d = document.createElement("div");
    d.textContent = t;
    return d.innerHTML;
}

function timeAgo(s) {
    if (!s) return "";
    try {
        const ms = Date.now() - new Date(s).getTime();
        const m = Math.floor(ms / 60000);
        const h = Math.floor(ms / 3600000);
        const d = Math.floor(ms / 86400000);
        if (m < 1) return "just now";
        if (m < 60) return `${m}m ago`;
        if (h < 24) return `${h}h ago`;
        if (d < 7) return `${d}d ago`;
        return new Date(s).toLocaleDateString("en-US", { month: "short", day: "numeric" });
    } catch (_) {
        return "";
    }
}

function num(id, target) {
    const el = document.getElementById(id);
    if (!el) return;

    const cur = parseInt(el.textContent, 10) || 0;
    if (cur === target) return;

    const diff = target - cur;
    const steps = Math.min(Math.abs(diff), 25) || 1;
    const step = diff / steps;
    let i = 0;

    const iv = setInterval(() => {
        i++;
        if (i >= steps) {
            el.textContent = target.toLocaleString();
            clearInterval(iv);
            return;
        }
        el.textContent = Math.round(cur + step * i).toLocaleString();
    }, 25);
}

function sevHex(s) {
    return (
        {
            critical: "rgba(239,68,68,0.5)",
            high: "rgba(245,158,11,0.5)",
            medium: "rgba(0,212,255,0.5)",
            low: "rgba(168,85,247,0.5)",
        }[s] || "rgba(144,144,168,0.3)"
    );
}

/* ─── Tab & Technical Console Logic ───────────────────────── */

function switchTheme(tabId) {
    if (graphState.tab === tabId) return;
    graphState.tab = tabId;

    document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
    const activeBtn = document.querySelector(`.tab-btn[onclick="switchTheme('${tabId}')"]`);
    if (activeBtn) activeBtn.classList.add("active");

    const visual = document.getElementById("tab-visual");
    const technical = document.getElementById("tab-technical");

    if (tabId === "visual") {
        if (visual) visual.style.display = "block";
        if (technical) technical.style.display = "none";
        if (G) G.resumeAnimation();
    } else {
        if (visual) visual.style.display = "none";
        if (technical) technical.style.display = "flex";
        if (G) G.pauseAnimation();
        loadTableData();
    }
}

async function loadTableData() {
    const btnRefresh = document.querySelector(".tech-controls .btn-outline");
    if (btnRefresh) {
        btnRefresh.disabled = true;
        btnRefresh.textContent = "Loading...";
    }

    const { source, category } = getFilters();
    let url = "/api/data?limit=2500";
    if (source) url += "&source=" + encodeURIComponent(source);
    if (category) url += "&category=" + encodeURIComponent(category);

    const res = await api(url);

    if (btnRefresh) {
        btnRefresh.disabled = false;
        btnRefresh.textContent = "Refresh Database";
    }

    if (res && res.items) {
        graphState.techData = res.items;
        
        const sources = new Set();
        const cats = new Set();
        graphState.techData.forEach((i) => {
            if (i.source) sources.add(i.source);
            if (i.category) cats.add(i.category);
        });
        
        const refill = (id, items, defaultText) => {
            const el = document.getElementById(id);
            if (!el) return;
            el.innerHTML = `<option value="">${defaultText}</option>`;
            Array.from(items).sort().forEach(val => {
                const opt = document.createElement("option");
                opt.value = val;
                opt.textContent = val;
                el.appendChild(opt);
            });
        };
        
        refill("tech-filter-source", sources, "All Sources");
        refill("tech-filter-category", cats, "All Categories");

        filterTechTable();
    } else {
        toast("Failed to load table data", "error");
    }
}

function filterTechTable() {
    const term = (document.getElementById("tech-search")?.value || "").toLowerCase();
    const fSource = document.getElementById("tech-filter-source")?.value || "";
    const fCat = document.getElementById("tech-filter-category")?.value || "";

    const filtered = graphState.techData.filter((i) => {
        if (fSource && i.source !== fSource) return false;
        if (fCat && i.category !== fCat) return false;
        if (term) {
            const sumChars = String(i.content || "").toLowerCase();
            if (!sumChars.includes(term)) return false;
        }
        return true;
    });

    const meta = document.getElementById("tech-meta");
    if (meta) meta.textContent = `Showing ${filtered.length.toLocaleString()} rows`;

    const body = document.getElementById("tech-table-body");
    if (!body) return;

    body.innerHTML = filtered.map((i) => {
        const d = timeAgo(i.collected_at);
        const linkHTML = i.url ? `<a href="${esc(i.url)}" target="_blank" style="color:var(--cyan)">↗ Link</a>` : "-";
        const contentStr = esc(String(i.content || ""));
        
        return `<tr>
            <td style="color:var(--text3)">${d}</td>
            <td style="color:var(--cyan)">${esc(i.source || "")}</td>
            <td style="color:var(--amber)">${esc(i.category || "")}</td>
            <td><div style="max-height:100px;overflow-y:hidden;text-overflow:ellipsis">${contentStr}</div></td>
            <td>${linkHTML}</td>
        </tr>`;
    }).join("");
}
