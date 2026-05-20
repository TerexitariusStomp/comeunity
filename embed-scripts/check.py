"""
Re-generate embeddings in a Cloudflare Pages-friendly format.
Stores embeddings as multiple small JSON files (one per chunk) with base64-encoded float16.
Each chunk is well under 25MB.
"""
import os, json, struct, base64, sqlite3

DB_PATH = r"C:\Users\terex\volunteer-map\backend\organizations.db"
META_PATH = r"C:\Users\terex\volunteer-map\frontend\data\embeddings-meta.json"
OUT_DIR = r"C:\Users\terex\volunteer-map\frontend\data"
CHUNK_SIZE = 2000  # records per chunk

def main():
    # Read metadata to get the embedding data
    # We need to regenerate from the original Python embedding script
    # But we deleted the original embeddings.json. Let's use a different approach.

    # Check what files exist
    print("Files in data dir:")
    for f in os.listdir(OUT_DIR):
        size = os.path.getsize(os.path.join(OUT_DIR, f)) / (1024*1024)
        print(f"  {f}: {size:.1f} MB")

    # Read the chunk files that exist
    chunk_files = sorted([f for f in os.listdir(OUT_DIR) if f.startswith("embeddings-") and f.endswith(".bin")])
    print(f"\nExisting chunks: {chunk_files}")

    # Check chunk sizes
    for cf in chunk_files:
        p = os.path.join(OUT_DIR, cf)
        size = os.path.getsize(p) / (1024*1024)
        print(f"  {cf}: {size:.1f} MB {'OK' if size < 25 else 'TOO LARGE'}")

if __name__ == "__main__":
    main()
