from pathlib import Path
from typing import Optional

from server.config import settings


class ImageStore:
    def __init__(self, base_dir: Optional[Path] = None):
        self.base_dir = base_dir or settings.images_dir

    def _path_for(self, session_id: str, topic: str, timestamp: float) -> Path:
        safe_topic = topic.lstrip("/").replace("/", "_")
        return self.base_dir / session_id / safe_topic / f"{timestamp:.6f}.jpg"

    def save(self, session_id: str, topic: str, timestamp: float, image_bytes: bytes) -> str:
        path = self._path_for(session_id, topic, timestamp)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(image_bytes)
        return str(path)

    def _validate_path(self, path: Path) -> Path:
        resolved = path.resolve()
        if not resolved.is_relative_to(self.base_dir.resolve()):
            raise ValueError(f"Path {path} is outside the image store directory")
        return resolved

    def load(self, path: str) -> Optional[bytes]:
        p = self._validate_path(Path(path))
        if p.exists():
            return p.read_bytes()
        return None

    def exists(self, path: str) -> bool:
        p = self._validate_path(Path(path))
        return p.exists()


image_store = ImageStore()
