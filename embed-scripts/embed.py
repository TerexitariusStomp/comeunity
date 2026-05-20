"""
Pre-compute embeddings for all organizations using sentence-transformers.
Reads organizations.db, generates name+description embeddings via all-MiniLM-L6-v2 (384-dim),
and writes a compact JSON file with id, lat, lon, and embedding vector.

Usage: python embed.py
Output: ../frontend/data/embeddings.json
"""
import json
import sqlite3
import sys
import os
import time

# Use the hermes-venv which has numpy but not sentence-transformers
# Use the system Python 3.11 which now has sentence-transformers
PYTHON = r"C:\Users\terex\AppData\Local\Programs\Python\Python311\python.exe"

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "backend", "organizations.db")
OUT_PATH = os.path.join(os.path.dirname(__file__), "..", "frontend", "data", "embeddings.json")
MODEL_NAME = "all-MiniLM-L6-v2"  # 384-dim, fast, good quality
BATCH_SIZE = 64


def main():
    # Read all organizations
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT id, name, description, latitude, longitude
        FROM organizations
        WHERE latitude IS NOT NULL AND longitude IS NOT NULL
    """).fetchall()
    conn.close()

    print(f"Loaded {len(rows)} organizations")

    # Format texts for embedding
    texts = []
    for r in rows:
        desc = (r["description"] or "")[:500]
        texts.append(f"{r['name']}. {desc}")

    # Load model and generate embeddings
    print(f"Loading model: {MODEL_NAME}")
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(MODEL_NAME)
    print(f"Model loaded. Embedding dimension: {model.get_sentence_embedding_dimension()}")

    all_embeddings = []
    total_batches = (len(texts) + BATCH_SIZE - 1) // BATCH_SIZE

    start = time.time()
    for i in range(0, len(texts), BATCH_SIZE):
        batch = texts[i:i + BATCH_SIZE]
        batch_num = i // BATCH_SIZE + 1

        vecs = model.encode(batch, show_progress_bar=False, normalize_embeddings=True)

        for j, vec in enumerate(vecs):
            row = rows[i + j]
            all_embeddings.append({
                "id": row["id"],
                "lat": row["latitude"],
                "lon": row["longitude"],
                "e": vec.tolist(),
            })

        elapsed = time.time() - start
        rate = len(all_embeddings) / elapsed
        remaining = (len(texts) - len(all_embeddings)) / rate
        print(f"\rBatch {batch_num}/{total_batches} | {len(all_embeddings)}/{len(texts)} | "
              f"{rate:.0f} docs/s | ETA: {remaining:.0f}s", end="", flush=True)

    print(f"\nGenerated {len(all_embeddings)} embeddings in {time.time() - start:.1f}s")

    # Write compact output
    output = {
        "model": MODEL_NAME,
        "dim": model.get_sentence_embedding_dimension(),
        "count": len(all_embeddings),
        "embeddings": all_embeddings,
    }

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w") as f:
        json.dump(output, f)

    size_mb = os.path.getsize(OUT_PATH) / (1024 * 1024)
    print(f"Written to {OUT_PATH} ({size_mb:.1f} MB)")


if __name__ == "__main__":
    main()
