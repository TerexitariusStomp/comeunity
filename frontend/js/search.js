/**
 * Client-side semantic search using pre-computed embeddings + WebLLM query embedding.
 *
 * Pre-computed embeddings (Python/sentence-transformers/all-MiniLM-L6-v2, uint8 quantized):
 *   - embeddings-index.json: {model, dim, count, num_chunks, range}
 *   - embeddings-000.json through embeddings-004.json: chunk files with {dim, count, offset, range, data: [{id, lat, lon, e}]}
 *
 * At runtime: WebLLM embeds the user's query, cosine similarity against pre-computed set.
 */

let embeddingIndex = null; // { embeddings: Float32Array, metadata: [{id, lat, lon}], count, dim, range }
let webllmEngine = null;

/**
 * Load all embedding chunks and reconstruct the full embedding matrix.
 */
async function loadEmbeddingIndex() {
  // Load index
  const indexResp = await fetch("data/embeddings-index.json");
  const index = await indexResp.json();

  const { dim, count, num_chunks, range } = index;
  const [vecMin, vecMax] = range;

  console.log(`Loading ${count} embeddings in ${num_chunks} chunks...`);

  // Load all chunks in parallel
  const chunkPromises = [];
  for (let i = 0; i < num_chunks; i++) {
    const chunkNum = String(i).padStart(3, "0");
    chunkPromises.push(
      fetch(`data/embeddings-${chunkNum}.json`).then((r) => r.json())
    );
  }
  const chunks = await Promise.all(chunkPromises);

  // Reconstruct full embedding matrix as Float32Array
  // Dequantize uint8 -> float32 on load
  const embeddings = new Float32Array(count * dim);
  const metadata = new Array(count);

  for (const chunk of chunks) {
    const { offset, data } = chunk;
    for (let i = 0; i < data.length; i++) {
      const item = data[i];
      const globalIdx = offset + i;

      // Decode base64 uint8 embedding
      const b64 = item.e;
      const binaryStr = atob(b64);
      const bytes = new Uint8Array(binaryStr.length);
      for (let j = 0; j < binaryStr.length; j++) {
        bytes[j] = binaryStr.charCodeAt(j);
      }

      // Dequantize: uint8 [0,255] -> float32 [vecMin, vecMax]
      const vecOffset = globalIdx * dim;
      const scale = (vecMax - vecMin) / 255.0;
      for (let j = 0; j < dim; j++) {
        embeddings[vecOffset + j] = bytes[j] * scale + vecMin;
      }

      metadata[globalIdx] = { id: item.id, lat: item.lat, lon: item.lon };
    }
  }

  console.log(`Loaded ${count} embeddings (dim=${dim})`);

  return { embeddings, metadata, count, dim };
}

/**
 * Initialize WebLLM embedding engine for query embedding.
 */
async function initWebLLMEngine() {
  const webllm = await import("https://esm.run/@mlc-ai/web-llm@0.2.83");
  const modelId = "snowflake-arctic-embed-m-q0f32-MLC-b4";

  const engine = await webllm.CreateMLCEngine(modelId, {
    initProgressCallback: (report) => {
      const label = document.getElementById("init-label");
      if (label) {
        label.style.display = "block";
        label.textContent = report.text;
      }
      console.log("[WebLLM]", report.text);
    },
    logLevel: "INFO",
  });

  console.log("WebLLM embedding engine ready");
  const label = document.getElementById("init-label");
  if (label) label.style.display = "none";
  return engine;
}

/**
 * Search: embed query via WebLLM, find top-k cosine similarity matches.
 */
async function searchEmbeddings(query, topK = 200) {
  if (!embeddingIndex) throw new Error("Embedding index not loaded");
  if (!webllmEngine) throw new Error("WebLLM engine not initialized");

  // Embed the query using WebLLM
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

  // Compute cosine similarities
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
