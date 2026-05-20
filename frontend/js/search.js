/**
 * Client-side semantic search using pre-computed embeddings + WebLLM query embedding.
 *
 * Pre-computed embeddings (Python/sentence-transformers/all-MiniLM-L6-v2):
 *   - embeddings.bin: base64-encoded float32 vectors [count * dim]
 *   - embeddings-meta.json: [{id, lat, lon}, ...]
 *
 * At runtime: WebLLM embeds the user's query, cosine similarity against pre-computed set.
 */

let embeddingIndex = null;
let webllmEngine = null;

/**
 * Load pre-computed embeddings from binary + metadata files.
 * Returns { embeddings: Float32Array, metadata: Array, count, dim }
 */
async function loadEmbeddingIndex() {
  // Load metadata and binary in parallel
  const [metaResp, binResp] = await Promise.all([
    fetch("data/embeddings-meta.json"),
    fetch("data/embeddings.bin"),
  ]);

  const metadata = await metaResp.json();
  const binText = await binResp.text();

  // Parse binary: first line is header JSON, rest is base64
  const newlineIdx = binText.indexOf("\n");
  const header = JSON.parse(binText.slice(0, newlineIdx));
  const b64 = binText.slice(newlineIdx + 1);

  // Decode base64 to Uint8Array, then to Float32Array
  const binaryStr = atob(b64);
  const bytes = new Uint8Array(binaryStr.length);
  for (let i = 0; i < binaryStr.length; i++) {
    bytes[i] = binaryStr.charCodeAt(i);
  }
  const embeddings = new Float32Array(bytes.buffer);

  console.log(
    `Loaded ${header.count} embeddings (dim=${header.dim}) from ${header.model}`
  );

  return {
    embeddings,
    metadata,
    count: header.count,
    dim: header.dim,
    model: header.model,
  };
}

/**
 * Initialize WebLLM embedding engine for query embedding.
 * Uses snowflake-arctic-embed-m (same model family as pre-computed embeddings).
 */
async function initWebLLMEngine() {
  // Dynamic import of WebLLM
  const webllm = await import(
    "https://esm.run/@mlc-ai/web-llm@0.2.83"
  );

  const modelId = "snowflake-arctic-embed-m-q0f32-MLC-b4";

  const engine = await webllm.CreateMLCEngine(modelId, {
    initProgressCallback: (report) => {
      const label = document.getElementById("init-label");
      if (label) label.textContent = report.text;
      console.log("[WebLLM]", report.text);
    },
    logLevel: "INFO",
  });

  console.log("WebLLM embedding engine ready");
  return engine;
}

/**
 * Search: embed query via WebLLM, find top-k cosine similarity matches.
 */
async function searchEmbeddings(query, topK = 200) {
  if (!embeddingIndex) {
    throw new Error("Embedding index not loaded");
  }
  if (!webllmEngine) {
    throw new Error("WebLLM engine not initialized");
  }

  // Embed the query
  const queryPrefix = "Represent this sentence for searching relevant passages: ";
  const reply = await webllmEngine.embeddings.create({
    input: [queryPrefix + query],
    model: "snowflake-arctic-embed-m-q0f32-MLC-b4",
  });

  // Normalize query vector
  const rawVec = reply.data[0].embedding;
  const queryVec = new Float32Array(rawVec.length);
  let norm = 0;
  for (let i = 0; i < rawVec.length; i++) norm += rawVec[i] * rawVec[i];
  norm = Math.sqrt(norm);
  for (let i = 0; i < rawVec.length; i++) queryVec[i] = rawVec[i] / norm;

  // Compute cosine similarities (pre-computed vectors are already normalized)
  const { embeddings, metadata, count, dim } = embeddingIndex;
  const scores = new Float32Array(count);

  for (let i = 0; i < count; i++) {
    const offset = i * dim;
    let dot = 0;
    for (let j = 0; j < dim; j++) {
      dot += queryVec[j] * embeddings[offset + j];
    }
    scores[i] = dot;
  }

  // Partial sort for top-k
  const indexed = new Array(count);
  for (let i = 0; i < count; i++) indexed[i] = { score: scores[i], idx: i };
  indexed.sort((a, b) => b.score - a.score);

  const results = [];
  const k = Math.min(topK, count);
  for (let i = 0; i < k; i++) {
    const { score, idx } = indexed[i];
    const meta = metadata[idx];
    results.push({
      id: meta.id,
      score: score,
      rank: i + 1,
      lat: meta.lat,
      lon: meta.lon,
    });
  }

  return results;
}
