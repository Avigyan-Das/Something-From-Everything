"""
Pydantic models for all data flowing through the system.
"""
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from enum import Enum
import uuid


class DataCategory(str, Enum):
    WORLD_NEWS = "world_news"
    TECHNOLOGY = "technology"
    SCIENCE = "science"
    FINANCE = "finance"
    SOCIAL = "social"
    WEATHER = "weather"
    GENERAL = "general"


class DataSource(str, Enum):
    RSS = "rss"
    WEB_SCRAPER = "web_scraper"
    REDDIT = "reddit"
    HACKERNEWS = "hackernews"
    FINANCE_API = "finance_api"
    WEATHER_API = "weather_api"


class SeverityLevel(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class DataItem(BaseModel):
    """A normalized piece of collected data from any source."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    title: str
    content: str
    url: Optional[str] = None
    source: DataSource
    category: DataCategory = DataCategory.GENERAL
    metadata: dict = Field(default_factory=dict)
    sentiment_score: Optional[float] = None
    collected_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        use_enum_values = True


class Insight(BaseModel):
    """A pattern or insight discovered by the analytics/agent system."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    title: str
    description: str
    insight_type: str  # e.g., "sentiment_spike", "correlation", "trend", "cluster"
    confidence: float = Field(ge=0.0, le=1.0)
    severity: SeverityLevel = SeverityLevel.INFO
    supporting_data: List[str] = Field(default_factory=list)  # IDs of related DataItems
    domains: List[str] = Field(default_factory=list)  # e.g., ["finance", "world_news"]
    recommended_actions: List[str] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    expires_at: Optional[datetime] = None

    class Config:
        use_enum_values = True


class Alert(BaseModel):
    """An alert triggered by insights meeting threshold criteria."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    insight_id: str
    title: str
    message: str
    severity: SeverityLevel
    acknowledged: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        use_enum_values = True


class AgentAction(BaseModel):
    """A logged action taken by an agent."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    agent_name: str
    action_type: str
    input_summary: str
    output_summary: str
    model_used: str = "qwen3.5-4b"
    tokens_used: int = 0
    duration_ms: int = 0
    created_at: datetime = Field(default_factory=datetime.utcnow)


class SystemStats(BaseModel):
    """Live system statistics for the dashboard."""
    total_data_items: int = 0
    total_insights: int = 0
    active_alerts: int = 0
    sources_active: int = 0
    last_collection: Optional[datetime] = None
    last_analysis: Optional[datetime] = None
    llm_status: str = "disconnected"
