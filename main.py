"""
Something from Everything — Main Entry Point

Multi-utility intelligence platform that collects open web data,
finds cross-domain patterns, and surfaces actionable insights.
"""
import asyncio
import logging
import os
import yaml
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from core.database import Database
from agents.llm_client import LLMClient
from agents.orchestrator import AgentOrchestrator
from collectors.rss_collector import RSSCollector
from collectors.web_scraper import WebScraperCollector
from collectors.social_collector import SocialCollector
from collectors.finance_collector import FinanceCollector
from collectors.weather_collector import WeatherCollector
from api.routes import router as api_router, set_dependencies, ws_endpoint

# ─── Logging ────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(name)-25s │ %(levelname)-7s │ %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("sfe")

# ─── Config ─────────────────────────────────────────────────────

def load_config(path: str = "config.yaml") -> dict:
    config_path = os.path.join(os.path.dirname(__file__), path)
    if os.path.exists(config_path):
        with open(config_path, "r") as f:
            return yaml.safe_load(f)
    logger.warning(f"Config not found at {config_path}, using defaults")
    return {}


# ─── App Setup ──────────────────────────────────────────────────

config = load_config()
db = Database(config.get("database", {}).get("path", "data/sfe.db"))
llm = LLMClient(config.get("llm", {}))
scheduler = AsyncIOScheduler()

# Initialize collectors
collectors = []
sources_cfg = config.get("sources", {})

if sources_cfg.get("rss", {}).get("enabled", True):
    collectors.append(RSSCollector(db, sources_cfg.get("rss", {})))

if sources_cfg.get("web_scraper", {}).get("enabled", True):
    collectors.append(WebScraperCollector(db, sources_cfg.get("web_scraper", {})))

if sources_cfg.get("social", {}).get("enabled", True):
    collectors.append(SocialCollector(db, sources_cfg.get("social", {})))

if sources_cfg.get("finance", {}).get("enabled", True):
    collectors.append(FinanceCollector(db, sources_cfg.get("finance", {})))

if sources_cfg.get("weather", {}).get("enabled", True):
    collectors.append(WeatherCollector(db, sources_cfg.get("weather", {})))

# Initialize orchestrator
orchestrator = AgentOrchestrator(db, llm, config)


# ─── Scheduled Jobs ─────────────────────────────────────────────

async def scheduled_collection():
    """Run all collectors on schedule."""
    logger.info("═══ Scheduled Collection Starting ═══")
    for collector in collectors:
        try:
            await collector.run()
        except Exception as e:
            logger.error(f"Scheduled collection error [{collector.name}]: {e}")


async def scheduled_analysis():
    """Run analysis pipeline on schedule."""
    logger.info("═══ Scheduled Analysis Starting ═══")
    try:
        await orchestrator.run_full_pipeline()
    except Exception as e:
        logger.error(f"Scheduled analysis error: {e}")


# ─── App Lifecycle ──────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("╔═══════════════════════════════════════════════╗")
    logger.info("║   Something from Everything — Starting Up     ║")
    logger.info("╚═══════════════════════════════════════════════╝")

    await db.initialize()
    logger.info("✓ Database initialized")

    # Check LLM connection
    llm_connected = await llm.check_connection()
    if llm_connected:
        logger.info("✓ KoboldCpp LLM connected")
    else:
        logger.warning("✗ KoboldCpp not available — agentic features disabled")
        logger.warning("  Start KoboldCpp with Qwen model to enable AI insights")

    # Set API dependencies
    set_dependencies(db, orchestrator, collectors, llm)

    # Schedule jobs
    collection_interval = sources_cfg.get("rss", {}).get("interval_minutes", 30)
    scheduler.add_job(scheduled_collection, 'interval', minutes=collection_interval,
                      id='collection', name='Data Collection')
    scheduler.add_job(scheduled_analysis, 'interval', minutes=collection_interval + 5,
                      id='analysis', name='Analysis Pipeline')
    scheduler.start()
    logger.info(f"✓ Scheduler started (collection every {collection_interval}min)")

    # Run initial collection
    logger.info("Running initial data collection...")
    await scheduled_collection()

    server_cfg = config.get("server", {})
    port = server_cfg.get("port", 8000)
    logger.info(f"✓ Dashboard available at http://localhost:{port}")
    logger.info("Ready! Press Ctrl+C to stop.")

    yield

    # Shutdown
    scheduler.shutdown()
    await db.close()
    logger.info("Shutdown complete.")


# ─── FastAPI App ────────────────────────────────────────────────

app = FastAPI(
    title="Something from Everything",
    description="Multi-utility intelligence platform",
    version="1.0.0",
    lifespan=lifespan
)

# Mount API routes
app.include_router(api_router)

# WebSocket route
app.add_api_websocket_route("/ws/live", ws_endpoint)

# Serve static files (dashboard)
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.get("/")
async def serve_dashboard():
    """Serve the main dashboard page."""
    index_path = os.path.join(static_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "Something from Everything API", "docs": "/docs"}


# ─── Run ────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    server_cfg = config.get("server", {})
    uvicorn.run(
        "main:app",
        host=server_cfg.get("host", "0.0.0.0"),
        port=server_cfg.get("port", 8000),
        reload=False,
        log_level="info"
    )
