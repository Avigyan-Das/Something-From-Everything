"""
Something from Everything - Main Entry Point

Multi-utility intelligence platform that collects open web data,
finds cross-domain patterns, and surfaces actionable insights.
"""
import logging
import os
import yaml
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from agents.llm_client import LLMClient
from agents.orchestrator import AgentOrchestrator
from api.routes import router as api_router, set_dependencies, ws_endpoint
from collectors.finance_collector import FinanceCollector
from collectors.rss_collector import RSSCollector
from collectors.social_collector import SocialCollector
from collectors.weather_collector import WeatherCollector
from collectors.web_scraper import WebScraperCollector
from core.database import Database
from core.firehose import CertStreamKeywordMonitor, WikipediaFirehose
from core.global_stream_jobs import run_gdelt_extremes_job, run_phish_tld_job


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)-25s | %(levelname)-7s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("sfe")


def load_config(path: str = "config.yaml") -> dict:
    config_path = os.path.join(os.path.dirname(__file__), path)
    if os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    logger.warning("Config not found at %s, using defaults", config_path)
    return {}


config = load_config()
db = Database(config.get("database", {}).get("path", "data/sfe.db"))
llm = LLMClient(config.get("llm", {}))
scheduler = AsyncIOScheduler()

sources_cfg = config.get("sources", {})
collectors = []

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

orchestrator = AgentOrchestrator(db, llm, config)

firehose_cfg = config.get("firehose", {})
wikipedia_firehose = WikipediaFirehose(
    db=db,
    stream_url=firehose_cfg.get(
        "stream_url", "wss://stream.wikimedia.org/v2/stream/recentchange"
    ),
    window_seconds=firehose_cfg.get("window_seconds", 300),
    flush_interval_seconds=firehose_cfg.get("flush_interval_seconds", 300),
    top_n=firehose_cfg.get("top_n", 3),
    reconnect_delay_seconds=firehose_cfg.get("reconnect_delay_seconds", 5),
)

certstream_cfg = config.get("certstream", {})
certstream_monitor = CertStreamKeywordMonitor(
    db=db,
    stream_url=certstream_cfg.get("stream_url", "wss://certstream.calidog.io/"),
    keywords=certstream_cfg.get("keywords", ["ai", "crypto", "login", "bank"]),
    flush_interval_seconds=certstream_cfg.get("flush_interval_seconds", 300),
    reconnect_delay_seconds=certstream_cfg.get("reconnect_delay_seconds", 5),
)

gdelt_cfg = config.get("gdelt", {})
phish_cfg = config.get("phish_feed", {})


async def scheduled_collection():
    """Run all collectors on schedule."""
    logger.info("=== Scheduled Collection Starting ===")
    for collector in collectors:
        try:
            await collector.run()
        except Exception as exc:
            logger.error("Scheduled collection error [%s]: %s", collector.name, exc)


async def scheduled_analysis():
    """Run analysis pipeline on schedule."""
    logger.info("=== Scheduled Analysis Starting ===")
    try:
        await orchestrator.run_full_pipeline()
    except Exception as exc:
        logger.error("Scheduled analysis error: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Something from Everything")

    await db.initialize()
    logger.info("Database initialized (WAL + pooled readers enabled)")

    llm_connected = await llm.check_connection()
    if llm_connected:
        logger.info("KoboldCpp LLM connected")
    else:
        logger.warning("KoboldCpp not available, agentic features disabled")

    set_dependencies(db, orchestrator, collectors, llm, config)

    collection_interval = sources_cfg.get("rss", {}).get("interval_minutes", 30)
    scheduler.add_job(
        scheduled_collection,
        "interval",
        minutes=collection_interval,
        id="collection",
        name="Data Collection",
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        scheduled_analysis,
        "interval",
        minutes=collection_interval + 5,
        id="analysis",
        name="Analysis Pipeline",
        max_instances=1,
        coalesce=True,
    )

    if gdelt_cfg.get("enabled", True):
        scheduler.add_job(
            run_gdelt_extremes_job,
            "interval",
            minutes=gdelt_cfg.get("interval_minutes", 15),
            id="gdelt_extremes",
            name="GDELT Extremes",
            kwargs={
                "db": db,
                "lastupdate_url": gdelt_cfg.get(
                    "lastupdate_url", "http://data.gdeltproject.org/gdeltv2/lastupdate.txt"
                ),
                "top_n": gdelt_cfg.get("top_n", 10),
            },
            max_instances=1,
            coalesce=True,
        )

    if phish_cfg.get("enabled", True):
        scheduler.add_job(
            run_phish_tld_job,
            "interval",
            minutes=phish_cfg.get("interval_minutes", 60),
            id="phish_tld",
            name="OpenPhish TLD Aggregation",
            kwargs={
                "db": db,
                "feed_url": phish_cfg.get("feed_url", "https://openphish.com/feed.txt"),
                "top_n": phish_cfg.get("top_n", 5),
            },
            max_instances=1,
            coalesce=True,
        )

    scheduler.start()
    logger.info("Scheduler started (collection every %s min)", collection_interval)

    if firehose_cfg.get("enabled", True):
        wikipedia_firehose.start()
        logger.info("Wikipedia firehose background task started")

    if certstream_cfg.get("enabled", True):
        certstream_monitor.start()
        logger.info("CertStream keyword monitor background task started")

    logger.info("Running initial data collection...")
    await scheduled_collection()

    server_cfg = config.get("server", {})
    port = server_cfg.get("port", 8000)
    logger.info("Dashboard available at http://localhost:%s", port)
    logger.info("Ready. Press Ctrl+C to stop.")

    yield

    if firehose_cfg.get("enabled", True):
        await wikipedia_firehose.stop()
        logger.info("Wikipedia firehose stopped")

    if certstream_cfg.get("enabled", True):
        await certstream_monitor.stop()
        logger.info("CertStream keyword monitor stopped")

    scheduler.shutdown()
    await db.close()
    logger.info("Shutdown complete")


app = FastAPI(
    title="Something from Everything",
    description="Multi-utility intelligence platform",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(api_router)
app.add_api_websocket_route("/ws/live", ws_endpoint)

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


if __name__ == "__main__":
    import uvicorn

    server_cfg = config.get("server", {})
    uvicorn.run(
        "main:app",
        host=server_cfg.get("host", "0.0.0.0"),
        port=server_cfg.get("port", 8000),
        reload=False,
        log_level="info",
    )
