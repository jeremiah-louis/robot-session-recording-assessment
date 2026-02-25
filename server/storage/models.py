from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


# --- Enums ---

class SessionStatus(str, Enum):
    recording = "recording"
    completed = "completed"
    disconnected = "disconnected"


class SessionSource(str, Enum):
    live = "live"
    imported = "import"


class SessionOutcome(str, Enum):
    success = "success"
    failure = "failure"


# --- Session models ---

class Session(BaseModel):
    session_id: str
    source: SessionSource
    dataset_name: Optional[str] = None
    episode_index: Optional[int] = None
    task: Optional[str] = None
    robot_type: Optional[str] = None
    fps: Optional[float] = None
    start_time: float
    end_time: Optional[float] = None
    total_frames: int = 0
    status: SessionStatus
    outcome: Optional[SessionOutcome] = None
    total_reward: Optional[float] = None
    features: Optional[Dict[str, Any]] = None
    summary: Optional[str] = None
    umap_x: Optional[float] = None
    umap_y: Optional[float] = None
    created_at: Optional[str] = None


class SessionListResponse(BaseModel):
    sessions: List[Session]
    total: int


# --- Message models ---

class Message(BaseModel):
    id: Optional[int] = None
    session_id: str
    timestamp: float
    topic: str
    data_type: str
    data: Optional[Any] = None
    image_path: Optional[str] = None
    frame_index: Optional[int] = None


# --- Topic models ---

class TopicSummary(BaseModel):
    session_id: str
    topic: str
    message_count: int
    first_time: float
    last_time: float
    avg_frequency: Optional[float] = None
    data_type: str
    shape: Optional[List[int]] = None
    feature_names: Optional[List[str]] = None


# --- Request models ---

class SeekRequest(BaseModel):
    start_time: float = Field(ge=0)
    end_time: float = Field(ge=0)
    topics: Optional[List[str]] = None
    limit: int = Field(default=1000, ge=1, le=10000)

    @field_validator("end_time")
    @classmethod
    def end_after_start(cls, v: float, info: Any) -> float:
        start_time = info.data.get("start_time")
        if start_time is not None and v <= start_time:
            raise ValueError("end_time must be greater than start_time")
        return v


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    limit: int = Field(default=10, ge=1, le=100)


# --- WebSocket message types ---

class WSSessionStart(BaseModel):
    type: str = "session_start"
    session_id: str
    robot_type: Optional[str] = None
    fps: Optional[float] = None
    topics: Optional[Dict[str, Dict[str, Any]]] = None


class WSTelemetryMessage(BaseModel):
    type: str = "message"
    topic: str
    timestamp: float
    data_type: str
    data: Optional[Any] = None
    image_base64: Optional[str] = None
    frame_index: Optional[int] = None


class WSSessionEnd(BaseModel):
    type: str = "session_end"


class WSBackpressure(BaseModel):
    type: str = "backpressure"
    action: str = "slow_down"


# --- Similarity / Graph models ---

class GraphNode(BaseModel):
    id: str
    label: str
    outcome: Optional[str] = None
    reward: Optional[float] = None
    x: float
    y: float


class GraphEdge(BaseModel):
    source: str
    target: str
    weight: float


class SimilarityGraphResponse(BaseModel):
    nodes: List[GraphNode]
    edges: List[GraphEdge]


# --- Search response ---

class SearchResult(BaseModel):
    session: Session
    score: float
