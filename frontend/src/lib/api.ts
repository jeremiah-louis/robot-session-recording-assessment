const BASE = "/api";

export interface Session {
  session_id: string;
  source: "live" | "import";
  dataset_name?: string;
  episode_index?: number;
  task?: string;
  robot_type?: string;
  fps?: number;
  start_time: number;
  end_time?: number;
  total_frames: number;
  status: "recording" | "completed" | "disconnected";
  outcome?: "success" | "failure";
  total_reward?: number;
  features?: Record<string, unknown>;
  summary?: string;
  umap_x?: number;
  umap_y?: number;
  created_at?: string;
}

export interface SessionListResponse {
  sessions: Session[];
  total: number;
}

export interface TopicSummary {
  session_id: string;
  topic: string;
  message_count: number;
  first_time: number;
  last_time: number;
  avg_frequency?: number;
  data_type: string;
  shape?: number[];
  feature_names?: string[];
}

export interface Message {
  id?: number;
  session_id: string;
  timestamp: number;
  topic: string;
  data_type: string;
  data?: unknown;
  image_path?: string;
  frame_index?: number;
}

export interface SearchResult {
  session: Session;
  score: number;
}

export interface GraphNode {
  id: string;
  label: string;
  outcome?: string;
  reward?: number;
  x: number;
  y: number;
}

export interface GraphEdge {
  source: string;
  target: string;
  weight: number;
}

export interface SimilarityGraphData {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

async function fetchJSON<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(BASE + url, init);
  if (!res.ok) {
    throw new Error(`${res.status} ${res.statusText}`);
  }
  return res.json();
}

export const api = {
  listSessions(source?: string, limit = 100, offset = 0) {
    const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
    if (source) params.set("source", source);
    return fetchJSON<SessionListResponse>(`/sessions?${params}`);
  },

  getSession(id: string) {
    return fetchJSON<Session>(`/sessions/${id}`);
  },

  getTopics(sessionId: string) {
    return fetchJSON<TopicSummary[]>(`/sessions/${sessionId}/topics`);
  },

  seek(sessionId: string, startTime: number, endTime: number, topics?: string[], limit = 1000) {
    return fetchJSON<Message[]>(`/sessions/${sessionId}/seek`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ start_time: startTime, end_time: endTime, topics, limit }),
    });
  },

  search(query: string, limit = 10) {
    return fetchJSON<SearchResult[]>(`/sessions/search`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query, limit }),
    });
  },

  getSimilar(sessionId: string, limit = 10) {
    return fetchJSON<SearchResult[]>(`/sessions/${sessionId}/similar?limit=${limit}`);
  },

  getSimilarityGraph() {
    return fetchJSON<SimilarityGraphData>(`/sessions/similarity-graph`);
  },

  getExportUrl(sessionId: string) {
    return `${BASE}/sessions/${sessionId}/export`;
  },

  getImageUrl(sessionId: string, topic: string, timestamp: number) {
    const topicPath = topic.startsWith("/") ? topic.slice(1) : topic;
    return `${BASE}/sessions/${sessionId}/images/${topicPath}/${timestamp}`;
  },
};
