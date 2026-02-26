import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket

from server.api import export, images, search, seek, sessions, topics
from server.ingestion.websocket_handler import handle_ingest
from server.storage.db import db

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.connect()
    logging.info("Database connected")
    yield
    db.close()
    logging.info("Database closed")


app = FastAPI(title="Robot Session Recording API", lifespan=lifespan)

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
