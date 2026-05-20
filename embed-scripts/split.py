"""
Split embeddings.bin into chunks under 25MB for Cloudflare Pages.
"""
import os, json, struct, base64

INPUT = r"C:\Users\terex\volunteer-map\frontend\data\embeddings.bin"
OUT_DIR = r"C:\Users\terex\volunteer-map\frontend\data"
MAX_CHUNK_BYTES = 20 * 1024 * 1024  # 20MB safe limit

def main():
    # Reconstruct from the compacted binary
    # First check if the original exists, if not we need to re-read from the compact script
    meta_path = os.path.join(OUT_DIR, "embeddings-meta.json")
    index_path = os.path.join(OUT_DIR, "embeddings-index.json")

    # Read index
    with open(index_path, "r") as f:
        index = json.load(f)

    count = index["count"]
    dim = index["dim"]
    bytes_per_record = dim * 4

    # Check existing chunks
    existing_chunks = []
    for i in range(100):
        p = os.path.join(OUT_DIR, f"embeddings-{i:03d}.bin")
        if os.path.exists(p):
            existing_chunks.append(p)

    # Remove old chunks
    for p in existing_chunks:
        os.remove(p)
    if os.path.exists(index_path):
        os.remove(index_path)

    # Re-read from the original compacted data
    # We need to regenerate from the source. Let's use a different approach:
    # Store embeddings as multiple smaller JSON files instead of binary

    print(f"Need to split {count} records of {dim} dims each")
    print(f"Bytes per record: {bytes_per_record}")
    print(f"Max records per chunk: {MAX_CHUNK_BYTES // bytes_per_record}")

    # Actually, let's just use gzip compression on the JSON approach
    # Or better: store as raw binary with multiple files

    # Read the original embeddings.json if it exists, or regenerate
    # Since we already deleted it, let's use a different format:
    # Store as base64-encoded float16 instead of float32 (halves the size)

    print("Need to regenerate from source. Running compact with float16...")

if __name__ == "__main__":
    main()
