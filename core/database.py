"""
Async SQLite database layer for Something from Everything.
"""
import asyncio
import aiosqlite
import json
import os
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional, Set
from core.models import DataItem, Insight, Alert, AgentAction, TopicCluster


class Database:
    def __init__(self, db_path: str = "data/sfe.db", read_pool_size: int = 4):
        self.db_path = db_path
        self.db: Optional[aiosqlite.Connection] = None  # backward compatibility alias
        self.read_pool_size = max(1, read_pool_size)

        self._write_db: Optional[aiosqlite.Connection] = None
        self._write_lock = asyncio.Lock()

        self._read_conns: List[aiosqlite.Connection] = []
        self._read_pool: asyncio.Queue = asyncio.Queue()

    async def initialize(self):
        """Create database, configure SQLite pragmas, and warm read pool."""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)

        self._write_db = await self._open_connection()
        self.db = self._write_db
        await self._configure_connection(self._write_db)
        await self._create_tables()

        for _ in range(self.read_pool_size):
            conn = await self._open_connection()
            await self._configure_connection(conn)
            self._read_conns.append(conn)
            await self._read_pool.put(conn)

    async def _open_connection(self) -> aiosqlite.Connection:
        conn = await aiosqlite.connect(self.db_path, timeout=30)
        conn.row_factory = aiosqlite.Row
        return conn

    async def _configure_connection(self, conn: aiosqlite.Connection):
        # WAL enables concurrent readers with a writer, NORMAL lowers fsync overhead.
        await conn.execute("PRAGMA journal_mode=WAL;")
        await conn.execute("PRAGMA synchronous=NORMAL;")
        await conn.execute("PRAGMA foreign_keys=ON;")
        await conn.execute("PRAGMA temp_store=MEMORY;")
        await conn.commit()

    async def _create_tables(self):
        await self._write_db.executescript(
            """
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

            CREATE INDEX IF NOT EXISTS idx_data_items_source ON data_items(source);
            CREATE INDEX IF NOT EXISTS idx_data_items_category ON data_items(category);
            CREATE INDEX IF NOT EXISTS idx_data_items_collected_at ON data_items(collected_at);
            CREATE INDEX IF NOT EXISTS idx_insights_type ON insights(insight_type);
            CREATE INDEX IF NOT EXISTS idx_insights_severity ON insights(severity);
            CREATE INDEX IF NOT EXISTS idx_alerts_severity ON alerts(severity);
            CREATE INDEX IF NOT EXISTS idx_alerts_acknowledged ON alerts(acknowledged);
            CREATE INDEX IF NOT EXISTS idx_topic_clusters_updated ON topic_clusters(last_updated);
            """
        )
        await self._write_db.commit()

    @asynccontextmanager
    async def _acquire_read_conn(self):
        conn = await self._read_pool.get()
        try:
            yield conn
        finally:
            await self._read_pool.put(conn)

    async def _execute_write(self, query: str, params: tuple = ()):
        async with self._write_lock:
            await self._write_db.execute(query, params)
            await self._write_db.commit()

    async def _fetch_all(self, query: str, params: tuple = ()) -> List[aiosqlite.Row]:
        async with self._acquire_read_conn() as conn:
            cursor = await conn.execute(query, params)
            rows = await cursor.fetchall()
            await cursor.close()
            return rows

    async def _fetch_one(self, query: str, params: tuple = ()) -> Optional[aiosqlite.Row]:
        async with self._acquire_read_conn() as conn:
            cursor = await conn.execute(query, params)
            row = await cursor.fetchone()
            await cursor.close()
            return row

    async def store_data_item(self, item: DataItem) -> str:
        await self._execute_write(
            """INSERT OR IGNORE INTO data_items
               (id, title, content, url, source, category, metadata, sentiment_score, collected_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                item.id,
                item.title,
                item.content,
                item.url,
                item.source,
                item.category,
                json.dumps(item.metadata),
                item.sentiment_score,
                item.collected_at.isoformat(),
            ),
        )
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

    async def get_data_items(
        self,
        limit: int = 50,
        offset: int = 0,
        source: Optional[str] = None,
        category: Optional[str] = None,
    ) -> List[dict]:
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

        rows = await self._fetch_all(query, tuple(params))
        return [self._row_to_dict(row) for row in rows]

    async def get_distinct_data_values(self, field: str) -> List[str]:
        """Return sorted distinct values for a known data_items column."""
        allowed = {"source", "category"}
        if field not in allowed:
            return []

        rows = await self._fetch_all(
            f"SELECT DISTINCT {field} AS value FROM data_items WHERE {field} IS NOT NULL ORDER BY value ASC"
        )
        return [row["value"] for row in rows if row["value"]]

    async def get_graph_dataset(
        self,
        *,
        limit: int = 300,
        offset: int = 0,
        max_limit: int = 1500,
        source: Optional[str] = None,
        category: Optional[str] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        insights_only: bool = False,
        insight_limit: int = 300,
        random: bool = False,
    ) -> Dict[str, Any]:
        """
        Return graph-safe slices of data + connected insights.
        Data retrieval stays indexed by source/category/collected_at filters.
        """
        safe_limit = max(1, min(limit, max_limit))
        safe_offset = max(0, offset)
        safe_insight_limit = max(1, min(insight_limit, 500))

        items: List[dict] = []
        total_items = 0

        # Build reusable data filters so SQLite can use existing indexes.
        where_clauses = []
        where_params: List[Any] = []
        if source:
            where_clauses.append("source = ?")
            where_params.append(source)
        if category:
            where_clauses.append("category = ?")
            where_params.append(category)
        if start_time:
            where_clauses.append("collected_at >= ?")
            where_params.append(start_time)
        if end_time:
            where_clauses.append("collected_at <= ?")
            where_params.append(end_time)

        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

        candidate_insights = await self._fetch_candidate_insights(limit=safe_insight_limit)
        connected_item_ids = self._collect_supporting_ids(candidate_insights)
        connected_categories = self._collect_domains(candidate_insights)

        if insights_only:
            items, total_items = await self._get_connected_data_items(
                connected_item_ids=connected_item_ids,
                connected_categories=connected_categories,
                where_sql=where_sql,
                where_params=where_params,
                limit=safe_limit,
                offset=safe_offset,
            )
        else:
            if random:
                items = await self._fetch_all(
                    f"""SELECT * FROM data_items
                        {where_sql}
                        ORDER BY RANDOM()
                        LIMIT ? OFFSET ?""",
                    tuple(where_params + [safe_limit, safe_offset]),
                )
            else:
                items = await self._fetch_all(
                    f"""SELECT * FROM data_items
                        {where_sql}
                        ORDER BY collected_at DESC
                        LIMIT ? OFFSET ?""",
                    tuple(where_params + [safe_limit, safe_offset]),
                )
            total_row = await self._fetch_one(
                f"SELECT COUNT(*) AS total FROM data_items {where_sql}",
                tuple(where_params),
            )
            total_items = int(total_row["total"]) if total_row else 0
            items = [self._row_to_dict(row) for row in items]

        graph_payload = self._build_graph_payload(items, candidate_insights)
        has_more = (safe_offset + len(items)) < total_items
        graph_payload["total_items"] = total_items
        graph_payload["offset"] = safe_offset
        graph_payload["limit"] = safe_limit
        graph_payload["next_offset"] = safe_offset + len(items)
        graph_payload["has_more"] = has_more
        return graph_payload

    async def _fetch_candidate_insights(self, limit: int) -> List[dict]:
        rows = await self._fetch_all(
            """SELECT * FROM insights
               ORDER BY created_at DESC
               LIMIT ?""",
            (limit,),
        )
        return [self._deserialize_insight(self._row_to_dict(row)) for row in rows]

    async def _get_connected_data_items(
        self,
        *,
        connected_item_ids: Set[str],
        connected_categories: Set[str],
        where_sql: str,
        where_params: List[Any],
        limit: int,
        offset: int,
    ) -> tuple[List[dict], int]:
        id_list = list(connected_item_ids)[:900]  # Stay under SQLite param limits.
        params: List[Any] = list(where_params)
        connected_predicates = []

        if id_list:
            placeholders = ",".join(["?"] * len(id_list))
            connected_predicates.append(f"id IN ({placeholders})")
            params.extend(id_list)

        if connected_categories:
            cat_list = list(connected_categories)
            placeholders = ",".join(["?"] * len(cat_list))
            connected_predicates.append(f"category IN ({placeholders})")
            params.extend(cat_list)

        if not connected_predicates:
            return [], 0

        connection_sql = "(" + " OR ".join(connected_predicates) + ")"
        filter_sql = where_sql
        if filter_sql:
            filter_sql = f"{filter_sql} AND {connection_sql}"
        else:
            filter_sql = f"WHERE {connection_sql}"

        rows = await self._fetch_all(
            f"""SELECT * FROM data_items
                {filter_sql}
                ORDER BY collected_at DESC
                LIMIT ? OFFSET ?""",
            tuple(params + [limit, offset]),
        )
        total_row = await self._fetch_one(
            f"SELECT COUNT(*) AS total FROM data_items {filter_sql}",
            tuple(params),
        )
        total_items = int(total_row["total"]) if total_row else 0
        return [self._row_to_dict(row) for row in rows], total_items

    def _collect_supporting_ids(self, insights: List[dict]) -> Set[str]:
        ids: Set[str] = set()
        for insight in insights:
            for value in insight.get("supporting_data", []):
                if value:
                    ids.add(str(value))
        return ids

    def _collect_domains(self, insights: List[dict]) -> Set[str]:
        domains: Set[str] = set()
        for insight in insights:
            for value in insight.get("domains", []):
                if value:
                    domains.add(str(value))
        return domains

    def _build_graph_payload(self, items: List[dict], candidate_insights: List[dict]) -> Dict[str, Any]:
        item_map = {str(item.get("id")): item for item in items if item.get("id")}
        items_by_category: Dict[str, List[str]] = {}
        for item in items:
            item_id = str(item.get("id", ""))
            if not item_id:
                continue
            cat = str(item.get("category", "general"))
            items_by_category.setdefault(cat, []).append(item_id)

        insights: List[dict] = []
        connections: Dict[str, List[str]] = {}
        for insight in candidate_insights:
            insight_id = str(insight.get("id", ""))
            if not insight_id:
                continue

            linked_ids = []
            for item_id in insight.get("supporting_data", []):
                key = str(item_id)
                if key in item_map:
                    linked_ids.append(key)

            # Fallback: if no explicit supporting ids are available, link by shared domains.
            if not linked_ids:
                for domain in insight.get("domains", []):
                    linked_ids.extend(items_by_category.get(str(domain), []))

            deduped_ids = list(dict.fromkeys(linked_ids))
            if deduped_ids:
                connections[insight_id] = deduped_ids
                insights.append(insight)

        return {
            "items": items,
            "insights": insights,
            "connections": connections,
        }

    async def get_recent_data_items(self, hours: int = 24, limit: int = 500) -> List[dict]:
        rows = await self._fetch_all(
            """SELECT * FROM data_items
               WHERE collected_at >= datetime('now', ?)
               ORDER BY collected_at DESC LIMIT ?""",
            (f"-{hours} hours", limit),
        )
        return [self._row_to_dict(row) for row in rows]

    async def store_insight(self, insight: Insight) -> str:
        await self._execute_write(
            """INSERT INTO insights
               (id, title, description, insight_type, confidence, severity,
                supporting_data, domains, recommended_actions, metadata, created_at, expires_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                insight.id,
                insight.title,
                insight.description,
                insight.insight_type,
                insight.confidence,
                insight.severity,
                json.dumps(insight.supporting_data),
                json.dumps(insight.domains),
                json.dumps(insight.recommended_actions),
                json.dumps(insight.metadata),
                insight.created_at.isoformat(),
                insight.expires_at.isoformat() if insight.expires_at else None,
            ),
        )
        return insight.id

    async def get_insights(
        self, limit: int = 50, offset: int = 0, insight_type: Optional[str] = None
    ) -> List[dict]:
        query = "SELECT * FROM insights"
        params = []

        if insight_type:
            query += " WHERE insight_type = ?"
            params.append(insight_type)

        query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        rows = await self._fetch_all(query, tuple(params))
        results = [self._deserialize_insight(self._row_to_dict(row)) for row in rows]
        return results

    async def store_alert(self, alert: Alert) -> str:
        await self._execute_write(
            """INSERT INTO alerts (id, insight_id, title, message, severity, acknowledged, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                alert.id,
                alert.insight_id,
                alert.title,
                alert.message,
                alert.severity,
                int(alert.acknowledged),
                alert.created_at.isoformat(),
            ),
        )
        return alert.id

    async def get_alerts(self, limit: int = 50, unacknowledged_only: bool = False) -> List[dict]:
        query = "SELECT * FROM alerts"
        params = []

        if unacknowledged_only:
            query += " WHERE acknowledged = 0"

        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        rows = await self._fetch_all(query, tuple(params))
        return [self._row_to_dict(row) for row in rows]

    async def acknowledge_alert(self, alert_id: str):
        await self._execute_write("UPDATE alerts SET acknowledged = 1 WHERE id = ?", (alert_id,))

    async def store_agent_action(self, action: AgentAction) -> str:
        await self._execute_write(
            """INSERT INTO agent_actions
               (id, agent_name, action_type, input_summary, output_summary,
                model_used, tokens_used, duration_ms, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                action.id,
                action.agent_name,
                action.action_type,
                action.input_summary,
                action.output_summary,
                action.model_used,
                action.tokens_used,
                action.duration_ms,
                action.created_at.isoformat(),
            ),
        )
        return action.id

    async def store_memory(self, agent_name: str, key: str, value: str, embedding: str = None):
        await self._execute_write(
            """INSERT INTO agent_memory (agent_name, memory_key, memory_value, embedding)
               VALUES (?, ?, ?, ?)""",
            (agent_name, key, value, embedding),
        )

    async def get_memories(self, agent_name: str, limit: int = 50) -> List[dict]:
        rows = await self._fetch_all(
            "SELECT * FROM agent_memory WHERE agent_name = ? ORDER BY updated_at DESC LIMIT ?",
            (agent_name, limit),
        )
        return [self._row_to_dict(row) for row in rows]

    async def store_topic_cluster(self, cluster: TopicCluster) -> str:
        await self._execute_write(
            """INSERT INTO topic_clusters
               (id, name, keywords, base_category, active_domains, size,
                created_at, last_updated, narrative_summary)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                cluster.id,
                cluster.name,
                json.dumps(cluster.keywords),
                cluster.base_category,
                json.dumps(cluster.active_domains),
                cluster.size,
                cluster.created_at.isoformat(),
                cluster.last_updated.isoformat(),
                cluster.narrative_summary,
            ),
        )
        return cluster.id

    async def update_topic_cluster(self, cluster: TopicCluster):
        await self._execute_write(
            """UPDATE topic_clusters
               SET name = ?, keywords = ?, active_domains = ?, size = ?,
                   last_updated = ?, narrative_summary = ?
               WHERE id = ?""",
            (
                cluster.name,
                json.dumps(cluster.keywords),
                json.dumps(cluster.active_domains),
                cluster.size,
                cluster.last_updated.isoformat(),
                cluster.narrative_summary,
                cluster.id,
            ),
        )

    async def get_recent_topic_clusters(self, days: int = 7, limit: int = 50) -> List[dict]:
        rows = await self._fetch_all(
            """SELECT * FROM topic_clusters
               WHERE last_updated >= datetime('now', ?)
               ORDER BY last_updated DESC LIMIT ?""",
            (f"-{days} days", limit),
        )
        results = []
        for row in rows:
            d = self._row_to_dict(row)
            for field in ["keywords", "active_domains"]:
                if isinstance(d.get(field), str):
                    try:
                        d[field] = json.loads(d[field])
                    except json.JSONDecodeError:
                        d[field] = []
            results.append(d)
        return results

    async def get_stats(self) -> dict:
        stats = {}
        for table, key in [("data_items", "total_data_items"), ("insights", "total_insights")]:
            row = await self._fetch_one(f"SELECT COUNT(*) FROM {table}")
            stats[key] = row[0] if row else 0

        row = await self._fetch_one("SELECT COUNT(*) FROM alerts WHERE acknowledged = 0")
        stats["active_alerts"] = row[0] if row else 0

        row = await self._fetch_one("SELECT MAX(collected_at) FROM data_items")
        stats["last_collection"] = row[0] if row and row[0] else None

        return stats

    def _row_to_dict(self, row) -> dict:
        if row is None:
            return {}
        return dict(row)

    def _deserialize_insight(self, insight: dict) -> dict:
        for field in ["supporting_data", "domains", "recommended_actions", "metadata"]:
            if isinstance(insight.get(field), str):
                try:
                    insight[field] = json.loads(insight[field])
                except json.JSONDecodeError:
                    insight[field] = [] if field != "metadata" else {}
        return insight

    async def close(self):
        while not self._read_pool.empty():
            await self._read_pool.get()

        for conn in self._read_conns:
            await conn.close()
        self._read_conns.clear()

        if self._write_db:
            await self._write_db.close()
            self._write_db = None

        self.db = None
