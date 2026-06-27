"""
Re-generate embeddings optimized for Cloudflare Pages.
Uses uint8 quantization (4x smaller than float32) + gzip-friendly JSON format.
Each chunk file is a small JSON with base64-encoded quantized vectors.
"""
import os, json, struct, base64, sqlite3, numpy as np

DB_PATH = "/home/user/volunteer-map/backend/organizations.db"
OUT_DIR = "/home/user/volunteer-map/frontend/data"
CHUNK_RECORDS = 3000  # records per chunk file

def main():
    # Clean up old chunk files
    for f in os.listdir(OUT_DIR):
        if f.startswith("embeddings-") and (f.endswith(".bin") or f.endswith(".json")):
            os.remove(os.path.join(OUT_DIR, f))
    for f in ["embeddings-index.json"]:
        p = os.path.join(OUT_DIR, f)
        if os.path.exists(p):
            os.remove(p)

    # Read organizations
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT id, name, description, latitude, longitude
        FROM organizations
        WHERE latitude IS NOT NULL AND longitude IS NOT NULL
    """).fetchall()
    conn.close()

    print(f"Loaded {len(rows)} organizations")

    # Format texts
    texts = []
    for r in rows:
        desc = (r["description"] or "")[:500]
        texts.append(f"{r['name']}. {desc}")

    # Generate embeddings
    print("Loading model...")
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer("all-MiniLM-L6-v2")
    print(f"Model loaded. Dim: {model.get_sentence_embedding_dimension()}")

    print("Generating embeddings...")
    vectors = model.encode(texts, show_progress_bar=True, normalize_embeddings=True)
    # vectors shape: (14803, 384), values in [-1, 1]

    # Quantize to uint8: map [-1, 1] -> [0, 255]
    quantized = ((vectors + 1.0) / 2.0 * 255).astype(np.uint8)

    # Compute min/max for dequantization
    vec_min = float(vectors.min())
    vec_max = float(vectors.max())
    print(f"Vector range: [{vec_min:.4f}, {vec_max:.4f}]")

    # Generate metadata from DB rows
    metadata = [{"id": r["id"], "lat": r["latitude"], "lon": r["longitude"]} for r in rows]

    # Write chunk files
    count = len(rows)
    dim = model.get_sentence_embedding_dimension()
    num_chunks = (count + CHUNK_RECORDS - 1) // CHUNK_RECORDS

    for chunk_idx in range(num_chunks):
        start = chunk_idx * CHUNK_RECORDS
        end = min(start + CHUNK_RECORDS, count)
        chunk_count = end - start

        chunk_data = []
        for i in range(start, end):
            # Store as base64-encoded uint8 bytes
            vec_bytes = quantized[i].tobytes()
            vec_b64 = base64.b64encode(vec_bytes).decode("ascii")
            chunk_data.append({
                "id": metadata[i]["id"],
                "lat": metadata[i]["lat"],
                "lon": metadata[i]["lon"],
                "e": vec_b64,
            })

        chunk_path = os.path.join(OUT_DIR, f"embeddings-{chunk_idx:03d}.json")
        with open(chunk_path, "w") as f:
            json.dump({
                "dim": dim,
                "count": chunk_count,
                "offset": start,
                "range": [vec_min, vec_max],
                "data": chunk_data,
            }, f)

        size_mb = os.path.getsize(chunk_path) / (1024 * 1024)
        print(f"  Chunk {chunk_idx}: {chunk_count} records ({size_mb:.1f} MB)")

    # Write index
    index = {
        "model": "all-MiniLM-L6-v2",
        "dim": dim,
        "count": count,
        "num_chunks": num_chunks,
        "range": [vec_min, vec_max],
    }
    with open(os.path.join(OUT_DIR, "embeddings-index.json"), "w") as f:
        json.dump(index, f)

    total_size = sum(
        os.path.getsize(os.path.join(OUT_DIR, f))
        for f in os.listdir(OUT_DIR)
        if f.startswith("embeddings-")
    ) / (1024 * 1024)

    print(f"\nTotal chunk size: {total_size:.1f} MB")
    print(f"Files: {num_chunks} chunks + index")

if __name__ == "__main__":
    main()
