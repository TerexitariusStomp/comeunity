"""
Convert embeddings.json (large JSON) to embeddings.bin (compact base64 binary).
The binary format is: header JSON line + base64-encoded float32 embeddings.
"""
import json
import base64
import struct
import os
import sys

INPUT = os.path.join(os.path.dirname(__file__), "..", "frontend", "data", "embeddings.json")
OUTPUT = os.path.join(os.path.dirname(__file__), "..", "frontend", "data", "embeddings.bin")
META_OUTPUT = os.path.join(os.path.dirname(__file__), "..", "frontend", "data", "embeddings-meta.json")

def main():
    print(f"Reading {INPUT}...")
    with open(INPUT, "r") as f:
        data = json.load(f)

    count = data["count"]
    dim = data["dim"]
    model = data["model"]
    embeddings = data["embeddings"]

    print(f"Count: {count}, Dim: {dim}, Model: {model}")

    # Build metadata (id, lat, lon for each embedding)
    metadata = []
    for e in embeddings:
        metadata.append({"id": e["id"], "lat": e["lat"], "lon": e["lon"]})

    # Write compact binary: all embeddings as contiguous float32, base64-encoded
    buf = bytearray()
    for e in embeddings:
        for val in e["e"]:
            buf.extend(struct.pack("<f", val))

    b64 = base64.b64encode(buf).decode("ascii")

    # Write binary file: header line + base64 data
    header = json.dumps({"model": model, "dim": dim, "count": count})
    with open(OUTPUT, "w") as f:
        f.write(header + "\n")
        f.write(b64)

    # Write metadata separately
    with open(META_OUTPUT, "w") as f:
        json.dump(metadata, f)

    bin_size = os.path.getsize(OUTPUT) / (1024 * 1024)
    meta_size = os.path.getsize(META_OUTPUT) / (1024 * 1024)
    print(f"Binary: {OUTPUT} ({bin_size:.1f} MB)")
    print(f"Metadata: {META_OUTPUT} ({meta_size:.1f} MB)")
    print(f"Total: {bin_size + meta_size:.1f} MB (was {os.path.getsize(INPUT) / (1024*1024):.1f} MB)")

    # Remove the old large JSON
    os.remove(INPUT)
    print(f"Removed {INPUT}")

if __name__ == "__main__":
    main()
