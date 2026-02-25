from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Paths
    data_dir: Path = Path("data")
    db_path: Path = Path("data/telemetry.duckdb")
    images_dir: Path = Path("data/images")

    # Server
    host: str = "0.0.0.0"
    port: int = 8000

    # OpenAI
    openai_api_key: str = ""
    embedding_model: str = "text-embedding-3-small"
    embedding_dim: int = 1536

    # Ingestion buffer
    buffer_max_size: int = 10000
    buffer_flush_size: int = 500
    buffer_flush_interval: float = 1.0

    # Similarity
    similarity_threshold: float = 0.7
    umap_n_neighbors: int = 15
    umap_min_dist: float = 0.1

    model_config = {
        "env_prefix": "ROBOT_",
        "env_file": ".env",
    }


settings = Settings()
