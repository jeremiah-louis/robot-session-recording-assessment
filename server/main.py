import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket

from server.api import export, images, search, seek, sessions, topics
from server.config import settings
from server.errors import register_error_handlers
from server.ingestion.websocket_handler import handle_ingest
from server.storage.db import db

logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.connect()
    logging.info("Database connected")
    yield
    db.close()
    logging.info("Database closed")


app = FastAPI(title="Robot Session Recording API", lifespan=lifespan)

register_error_handlers(app)

app.include_router(export.router)
app.include_router(images.router)
app.include_router(search.router)
app.include_router(seek.router)
app.include_router(sessions.router)
app.include_router(topics.router)


@app.websocket("/ws/ingest")
async def ws_ingest(ws: WebSocket):
    await handle_ingest(ws)


@app.get("/health")
async def health():
    return {"status": "ok"}
