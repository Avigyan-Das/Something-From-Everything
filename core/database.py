"""
Async SQLite database layer for Something from Everything.
"""
import aiosqlite
import json
import os
from datetime import datetime
from typing import List, Optional
from core.models import DataItem, Insight, Alert, AgentAction, TopicCluster


class Database:
    def __init__(self, db_path: str = "data/sfe.db"):
        self.db_path = db_path
        self.db: Optional[aiosqlite.Connection] = None

    async def initialize(self):
        """Create database and tables."""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self.db = await aiosqlite.connect(self.db_path)
        self.db.row_factory = aiosqlite.Row
        await self._create_tables()

    async def _create_tables(self):
        await self.db.executescript("""
            CREATE TABLE IF NOT EXISTS data_items (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                url TEXT,
                source TEXT NOT NULL,
                category TEXT DEFAULT 'general',
                metadata TEXT DEFAULT '{}',
                sentiment_score REAL,
                collected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS insights (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                insight_type TEXT NOT NULL,
                confidence REAL DEFAULT 0.5,
                severity TEXT DEFAULT 'info',
                supporting_data TEXT DEFAULT '[]',
                domains TEXT DEFAULT '[]',
                recommended_actions TEXT DEFAULT '[]',
                metadata TEXT DEFAULT '{}',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS alerts (
                id TEXT PRIMARY KEY,
                insight_id TEXT,
                title TEXT NOT NULL,
                message TEXT NOT NULL,
                severity TEXT DEFAULT 'info',
                acknowledged INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (insight_id) REFERENCES insights(id)
            );

            CREATE TABLE IF NOT EXISTS agent_actions (
                id TEXT PRIMARY KEY,
                agent_name TEXT NOT NULL,
                action_type TEXT NOT NULL,
                input_summary TEXT,
                output_summary TEXT,
                model_used TEXT DEFAULT 'qwen3.5-4b',
                tokens_used INTEGER DEFAULT 0,
                duration_ms INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS agent_memory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_name TEXT NOT NULL,
                memory_key TEXT NOT NULL,
                memory_value TEXT NOT NULL,
                embedding TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_data_items_source ON data_items(source);
            CREATE INDEX IF NOT EXISTS idx_data_items_category ON data_items(category);
            CREATE INDEX IF NOT EXISTS idx_data_items_collected_at ON data_items(collected_at);
            CREATE INDEX IF NOT EXISTS idx_insights_type ON insights(insight_type);
            CREATE INDEX IF NOT EXISTS idx_insights_severity ON insights(severity);
            CREATE INDEX IF NOT EXISTS idx_alerts_severity ON alerts(severity);
            CREATE INDEX IF NOT EXISTS idx_alerts_acknowledged ON alerts(acknowledged);
            
            CREATE TABLE IF NOT EXISTS topic_clusters (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                keywords TEXT NOT NULL,
                base_category TEXT DEFAULT 'general',
                active_domains TEXT DEFAULT '[]',
                size INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                narrative_summary TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_topic_clusters_updated ON topic_clusters(last_updated);
        """)
        await self.db.commit()

    # ─── Data Items ──────────────────────────────────────────────────

    async def store_data_item(self, item: DataItem) -> str:
        await self.db.execute(
            """INSERT OR IGNORE INTO data_items 
               (id, title, content, url, source, category, metadata, sentiment_score, collected_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (item.id, item.title, item.content, item.url, item.source,
             item.category, json.dumps(item.metadata), item.sentiment_score,
             item.collected_at.isoformat())
        )
        await self.db.commit()
        return item.id

    async def store_data_items(self, items: List[DataItem]) -> int:
        count = 0
        for item in items:
            try:
                await self.store_data_item(item)
                count += 1
            except Exception:
                pass
        return count

    async def get_data_items(self, limit: int = 50, offset: int = 0,
                              source: Optional[str] = None,
                              category: Optional[str] = None) -> List[dict]:
        query = "SELECT * FROM data_items"
        params = []
        conditions = []

        if source:
            conditions.append("source = ?")
            params.append(source)
        if category:
            conditions.append("category = ?")
            params.append(category)

        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        query += " ORDER BY collected_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        cursor = await self.db.execute(query, params)
        rows = await cursor.fetchall()
        return [self._row_to_dict(row) for row in rows]

    async def get_recent_data_items(self, hours: int = 24, limit: int = 500) -> List[dict]:
        cursor = await self.db.execute(
            """SELECT * FROM data_items 
               WHERE collected_at >= datetime('now', ?) 
               ORDER BY collected_at DESC LIMIT ?""",
            (f'-{hours} hours', limit)
        )
        rows = await cursor.fetchall()
        return [self._row_to_dict(row) for row in rows]

    # ─── Insights ────────────────────────────────────────────────────

    async def store_insight(self, insight: Insight) -> str:
        await self.db.execute(
            """INSERT INTO insights 
               (id, title, description, insight_type, confidence, severity,
                supporting_data, domains, recommended_actions, metadata, created_at, expires_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (insight.id, insight.title, insight.description, insight.insight_type,
             insight.confidence, insight.severity,
             json.dumps(insight.supporting_data), json.dumps(insight.domains),
             json.dumps(insight.recommended_actions), json.dumps(insight.metadata),
             insight.created_at.isoformat(),
             insight.expires_at.isoformat() if insight.expires_at else None)
        )
        await self.db.commit()
        return insight.id

    async def get_insights(self, limit: int = 50, offset: int = 0,
                           insight_type: Optional[str] = None) -> List[dict]:
        query = "SELECT * FROM insights"
        params = []

        if insight_type:
            query += " WHERE insight_type = ?"
            params.append(insight_type)

        query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        cursor = await self.db.execute(query, params)
        rows = await cursor.fetchall()
        results = []
        for row in rows:
            d = self._row_to_dict(row)
            for field in ['supporting_data', 'domains', 'recommended_actions', 'metadata']:
                if isinstance(d.get(field), str):
                    try:
                        d[field] = json.loads(d[field])
                    except json.JSONDecodeError:
                        pass
            results.append(d)
        return results

    # ─── Alerts ──────────────────────────────────────────────────────

    async def store_alert(self, alert: Alert) -> str:
        await self.db.execute(
            """INSERT INTO alerts (id, insight_id, title, message, severity, acknowledged, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (alert.id, alert.insight_id, alert.title, alert.message,
             alert.severity, int(alert.acknowledged), alert.created_at.isoformat())
        )
        await self.db.commit()
        return alert.id

    async def get_alerts(self, limit: int = 50, unacknowledged_only: bool = False) -> List[dict]:
        query = "SELECT * FROM alerts"
        params = []

        if unacknowledged_only:
            query += " WHERE acknowledged = 0"

        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        cursor = await self.db.execute(query, params)
        rows = await cursor.fetchall()
        return [self._row_to_dict(row) for row in rows]

    async def acknowledge_alert(self, alert_id: str):
        await self.db.execute(
            "UPDATE alerts SET acknowledged = 1 WHERE id = ?", (alert_id,)
        )
        await self.db.commit()

    # ─── Agent Actions ───────────────────────────────────────────────

    async def store_agent_action(self, action: AgentAction) -> str:
        await self.db.execute(
            """INSERT INTO agent_actions 
               (id, agent_name, action_type, input_summary, output_summary,
                model_used, tokens_used, duration_ms, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (action.id, action.agent_name, action.action_type,
             action.input_summary, action.output_summary,
             action.model_used, action.tokens_used, action.duration_ms,
             action.created_at.isoformat())
        )
        await self.db.commit()
        return action.id

    # ─── Agent Memory ────────────────────────────────────────────────

    async def store_memory(self, agent_name: str, key: str, value: str, embedding: str = None):
        await self.db.execute(
            """INSERT INTO agent_memory (agent_name, memory_key, memory_value, embedding)
               VALUES (?, ?, ?, ?)""",
            (agent_name, key, value, embedding)
        )
        await self.db.commit()

    async def get_memories(self, agent_name: str, limit: int = 50) -> List[dict]:
        cursor = await self.db.execute(
            "SELECT * FROM agent_memory WHERE agent_name = ? ORDER BY updated_at DESC LIMIT ?",
            (agent_name, limit)
        )
        rows = await cursor.fetchall()
        return [self._row_to_dict(row) for row in rows]

    # ─── Topic Clusters ──────────────────────────────────────────────
    
    async def store_topic_cluster(self, cluster: TopicCluster) -> str:
        await self.db.execute(
            """INSERT INTO topic_clusters 
               (id, name, keywords, base_category, active_domains, size, 
                created_at, last_updated, narrative_summary)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (cluster.id, cluster.name, json.dumps(cluster.keywords), cluster.base_category,
             json.dumps(cluster.active_domains), cluster.size, 
             cluster.created_at.isoformat(), cluster.last_updated.isoformat(),
             cluster.narrative_summary)
        )
        await self.db.commit()
        return cluster.id

    async def update_topic_cluster(self, cluster: TopicCluster):
        await self.db.execute(
            """UPDATE topic_clusters 
               SET name = ?, keywords = ?, active_domains = ?, size = ?, 
                   last_updated = ?, narrative_summary = ?
               WHERE id = ?""",
            (cluster.name, json.dumps(cluster.keywords), json.dumps(cluster.active_domains),
             cluster.size, cluster.last_updated.isoformat(), 
             cluster.narrative_summary, cluster.id)
        )
        await self.db.commit()

    async def get_recent_topic_clusters(self, days: int = 7, limit: int = 50) -> List[dict]:
        cursor = await self.db.execute(
            """SELECT * FROM topic_clusters 
               WHERE last_updated >= datetime('now', ?) 
               ORDER BY last_updated DESC LIMIT ?""",
            (f'-{days} days', limit)
        )
        rows = await cursor.fetchall()
        results = []
        for row in rows:
            d = self._row_to_dict(row)
            for field in ['keywords', 'active_domains']:
                if isinstance(d.get(field), str):
                    try:
                        d[field] = json.loads(d[field])
                    except json.JSONDecodeError:
                        d[field] = []
            results.append(d)
        return results

    # ─── Stats ───────────────────────────────────────────────────────

    async def get_stats(self) -> dict:
        stats = {}
        for table, key in [("data_items", "total_data_items"),
                           ("insights", "total_insights")]:
            cursor = await self.db.execute(f"SELECT COUNT(*) FROM {table}")
            row = await cursor.fetchone()
            stats[key] = row[0] if row else 0

        cursor = await self.db.execute(
            "SELECT COUNT(*) FROM alerts WHERE acknowledged = 0"
        )
        row = await cursor.fetchone()
        stats["active_alerts"] = row[0] if row else 0

        cursor = await self.db.execute(
            "SELECT MAX(collected_at) FROM data_items"
        )
        row = await cursor.fetchone()
        stats["last_collection"] = row[0] if row and row[0] else None

        return stats

    # ─── Helpers ─────────────────────────────────────────────────────

    def _row_to_dict(self, row) -> dict:
        if row is None:
            return {}
        return dict(row)

    async def close(self):
        if self.db:
            await self.db.close()
