"""
FastAPI API routes and WebSocket endpoint.
"""
import json
import asyncio
import logging
from typing import List, Optional
from datetime import datetime
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")

# Will be set by main.py on startup
_db = None
_orchestrator = None
_collectors = None
_llm = None
_ws_clients: List[WebSocket] = []


def set_dependencies(db, orchestrator, collectors, llm):
    global _db, _orchestrator, _collectors, _llm
    _db = db
    _orchestrator = orchestrator
    _collectors = collectors
    _llm = llm


# ─── Data Endpoints ──────────────────────────────────────────────

@router.get("/data")
async def get_data(limit: int = Query(500, ge=1, le=1500),
                   offset: int = Query(0, ge=0),
                   source: Optional[str] = None,
                   category: Optional[str] = None):
    """Get collected data items with optional filters."""
    items = await _db.get_data_items(limit=limit, offset=offset,
                                      source=source, category=category)
    return {"items": items, "count": len(items)}


@router.get("/data/recent")
async def get_recent_data(hours: int = Query(24, ge=1, le=168)):
    """Get data items from the last N hours."""
    items = await _db.get_recent_data_items(hours=hours)
    return {"items": items, "count": len(items)}


# ─── Insights Endpoints ─────────────────────────────────────────

@router.get("/insights")
async def get_insights(limit: int = Query(50, ge=1, le=200),
                       offset: int = Query(0, ge=0),
                       insight_type: Optional[str] = None):
    """Get generated insights."""
    insights = await _db.get_insights(limit=limit, offset=offset,
                                       insight_type=insight_type)
    return {"insights": insights, "count": len(insights)}


# ─── Alerts Endpoints ────────────────────────────────────────────

@router.get("/alerts")
async def get_alerts(limit: int = Query(50, ge=1, le=200),
                     unacknowledged_only: bool = Query(False)):
    """Get alerts."""
    alerts = await _db.get_alerts(limit=limit, unacknowledged_only=unacknowledged_only)
    return {"alerts": alerts, "count": len(alerts)}


@router.post("/alerts/{alert_id}/acknowledge")
async def acknowledge_alert(alert_id: str):
    """Acknowledge an alert."""
    await _db.acknowledge_alert(alert_id)
    return {"status": "acknowledged"}


# ─── Action Endpoints ────────────────────────────────────────────

@router.post("/collect/now")
async def trigger_collection():
    """Trigger immediate data collection from all sources."""
    results = {}
    for collector in _collectors:
        try:
            count = await collector.run()
            results[collector.name] = count
        except Exception as e:
            results[collector.name] = f"error: {str(e)}"

    # Broadcast update to WebSocket clients
    await broadcast_ws({
        "type": "collection_complete",
        "data": results,
        "timestamp": datetime.utcnow().isoformat()
    })

    return {"status": "complete", "results": results}


@router.post("/analyze/now")
async def trigger_analysis():
    """Trigger immediate analysis pipeline."""
    try:
        results = await _orchestrator.run_full_pipeline()

        # Broadcast update
        await broadcast_ws({
            "type": "analysis_complete",
            "data": results,
            "timestamp": datetime.utcnow().isoformat()
        })

        return {"status": "complete", "results": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─── Stats & Status ─────────────────────────────────────────────

@router.get("/stats")
async def get_stats():
    """Get system statistics."""
    db_stats = await _db.get_stats()
    llm_status = await _llm.get_status() if _llm else {"connected": False}

    return {
        **db_stats,
        "sources_active": len(_collectors) if _collectors else 0,
        "llm_status": "connected" if llm_status.get("connected") else "disconnected",
        "llm_info": llm_status,
    }


@router.get("/sources")
async def get_sources():
    """Get configured data sources."""
    sources = []
    if _collectors:
        for c in _collectors:
            sources.append({
                "name": c.name,
                "type": c.name,
                "enabled": True,
            })
    return {"sources": sources}


# ─── WebSocket ───────────────────────────────────────────────────

async def ws_endpoint(websocket: WebSocket):
    """WebSocket endpoint for live dashboard updates."""
    await websocket.accept()
    _ws_clients.append(websocket)
    logger.info(f"WebSocket client connected. Total: {len(_ws_clients)}")

    try:
        # Send initial stats
        stats = await _db.get_stats()
        await websocket.send_json({
            "type": "stats",
            "data": stats,
            "timestamp": datetime.utcnow().isoformat()
        })

        while True:
            # Keep connection alive, listen for messages
            data = await websocket.receive_text()
            # Handle client messages if needed
            msg = json.loads(data) if data else {}
            if msg.get("type") == "ping":
                await websocket.send_json({"type": "pong"})

    except WebSocketDisconnect:
        _ws_clients.remove(websocket)
        logger.info(f"WebSocket client disconnected. Total: {len(_ws_clients)}")
    except Exception as e:
        if websocket in _ws_clients:
            _ws_clients.remove(websocket)
        logger.error(f"WebSocket error: {e}")


async def broadcast_ws(message: dict):
    """Broadcast a message to all connected WebSocket clients."""
    disconnected = []
    for client in _ws_clients:
        try:
            await client.send_json(message)
        except Exception:
            disconnected.append(client)

    for client in disconnected:
        if client in _ws_clients:
            _ws_clients.remove(client)
