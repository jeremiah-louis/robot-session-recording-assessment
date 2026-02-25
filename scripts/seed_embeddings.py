"""Seed script: generate summaries, embeddings, metrics vectors, and UMAP coords for all sessions.

Usage:
    python -m scripts.seed_embeddings [--batch-size 50]
"""

import argparse
import asyncio
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


async def seed(batch_size: int = 50):
    from server.ai.embeddings import (
        generate_embeddings_batch,
        generate_session_summary,
    )
    from server.ai.similarity import compute_metrics_vector, compute_umap_projection
    from server.storage.db import db

    db.connect()

    try:
        # Get all sessions
        sessions = await db.read("SELECT session_id, summary, source FROM sessions ORDER BY created_at")
        total = len(sessions)
        logger.info(f"Found {total} sessions to process")

        if total == 0:
            logger.info("No sessions found. Import data first.")
            return

        # Step 1: Generate summaries for sessions that don't have one
        logger.info("--- Step 1: Generating summaries ---")
        no_summary = [s for s in sessions if not s.get("summary")]
        for i, s in enumerate(no_summary):
            summary = await generate_session_summary(s["session_id"])
            if summary:
                logger.info(f"  [{i+1}/{len(no_summary)}] {s['session_id'][:8]}: {summary[:80]}...")
        logger.info(f"Generated {len(no_summary)} summaries")

        # Step 2: Generate embeddings in batches
        logger.info("--- Step 2: Generating embeddings ---")
        # Re-fetch to get summaries
        sessions = await db.read(
            "SELECT session_id, summary FROM sessions WHERE summary IS NOT NULL AND embedding IS NULL ORDER BY created_at"
        )
        logger.info(f"  {len(sessions)} sessions need embeddings")

        for batch_start in range(0, len(sessions), batch_size):
            batch = sessions[batch_start : batch_start + batch_size]
            texts = [s["summary"] for s in batch]
            ids = [s["session_id"] for s in batch]

            embeddings = await generate_embeddings_batch(texts)

            for sid, emb in zip(ids, embeddings):
                await db.update_session(sid, {"embedding": emb})

            logger.info(f"  Embedded batch {batch_start // batch_size + 1} ({len(batch)} sessions)")

        # Step 3: Compute metrics vectors
        logger.info("--- Step 3: Computing metrics vectors ---")
        all_sessions = await db.read("SELECT session_id FROM sessions WHERE metrics_vec IS NULL")
        for i, s in enumerate(all_sessions):
            await compute_metrics_vector(s["session_id"])
            if (i + 1) % 20 == 0:
                logger.info(f"  Metrics: {i+1}/{len(all_sessions)}")
        logger.info(f"Computed {len(all_sessions)} metrics vectors")

        # Step 4: UMAP projection
        logger.info("--- Step 4: Computing UMAP projection ---")
        await compute_umap_projection()
        logger.info("UMAP projection complete")

        # Final stats
        stats = await db.read_one(
            """
            SELECT
                COUNT(*) as total,
                COUNT(summary) as with_summary,
                COUNT(embedding) as with_embedding,
                COUNT(metrics_vec) as with_metrics,
                COUNT(umap_x) as with_umap
            FROM sessions
            """
        )
        logger.info(f"Final stats: {stats}")

    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(description="Seed embeddings and similarity data")
    parser.add_argument("--batch-size", type=int, default=50, help="Embedding batch size")
    args = parser.parse_args()

    asyncio.run(seed(batch_size=args.batch_size))


if __name__ == "__main__":
    main()
