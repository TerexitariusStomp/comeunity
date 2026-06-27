/**
 * Client-side semantic search using pre-computed embeddings + in-browser query embedding.
 *
 * Pre-computed embeddings (Python/sentence-transformers/all-MiniLM-L6-v2, uint8 quantized):
 *   - embeddings-index.json: {model, dim, count, num_chunks, range}
 *   - embeddings-000.json: chunk files with {dim, count, offset, range, data: [{id, lat, lon, e}]}
 *
 * At runtime: Transformers.js (WASM) or WebLLM (WebGPU) embeds the user's query,
 * cosine similarity against pre-computed set.
 */

let embeddingIndex = null;
let webllmEngine = null;
let transformersPipeline = null;
let initProgressCb = null;
window.setInitProgressCb = (cb) => { initProgressCb = cb; };
window.getEmbeddingIndex = () => embeddingIndex;
window.getWebllmEngine = () => webllmEngine;
window.setWebllmEngine = (e) => { webllmEngine = e; };

/**
 * Initialize Transformers.js pipeline directly (no worker) - works via WASM in most browsers.
 */
async function initTransformers() {
  if (transformersPipeline) return transformersPipeline;
  const { pipeline, env } = await import('https://cdn.jsdelivr.net/npm/@xenova/transformers@2.17.2');
  env.allowLocalModels = false;
  transformersPipeline = await pipeline('feature-extraction', 'Xenova/all-MiniLM-L6-v2', {
    progress_callback: (data) => {
      if (initProgressCb && data.status) {
        initProgressCb(data);
      }
    }
  });
  return transformersPipeline;
}

async function queryEmbeddingWithTransformers(text) {
  const extractor = await initTransformers();
  const output = await extractor(text, { pooling: 'mean', normalize: true });
  return new Float32Array(output.data);
}

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

  embeddingIndex = { embeddings, metadata, count, dim };
  return embeddingIndex;
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
 * Search: embed query via WebLLM (WebGPU) or Transformers.js (WASM), find top-k cosine similarity matches.
 * Falls back to keyword-based search only if both ML approaches fail.
 */
async function searchEmbeddings(query, topK = 200) {
  if (!embeddingIndex) throw new Error("Embedding index not loaded");

  let queryVec = null;

  // Try WebLLM first (fast, needs WebGPU)
  if (webllmEngine) {
    try {
      console.log('[search] Using WebLLM (WebGPU) for query embedding');
      const queryPrefix = "Represent this sentence for searching relevant passages: ";
      const reply = await webllmEngine.embeddings.create({
        input: [queryPrefix + query],
        model: "snowflake-arctic-embed-m-q0f32-MLC-b4",
      });
      const rawVec = reply.data[0].embedding;
      queryVec = new Float32Array(rawVec.length);
      let norm = 0;
      for (let i = 0; i < rawVec.length; i++) norm += rawVec[i] * rawVec[i];
      norm = Math.sqrt(norm);
      for (let i = 0; i < rawVec.length; i++) queryVec[i] = rawVec[i] / norm;
      console.log('[search] WebLLM query embedding done, dim:', queryVec.length);
    } catch (err) {
      console.error('[search] WebLLM embedding failed:', err);
      webllmEngine = null;
    }
  }

  // Try Transformers.js (WASM, works in most browsers)
  if (!queryVec) {
    try {
      console.log('[search] Using Transformers.js (WASM) for query embedding');
      queryVec = await queryEmbeddingWithTransformers(query);
      console.log('[search] Transformers.js query embedding done, dim:', queryVec.length);
    } catch (err) {
      console.error('[search] Transformers.js embedding failed:', err);
    }
  }

  // If we have a query vector, use cosine similarity
  if (queryVec) {
    console.log('[search] Computing cosine similarity against 1113 pre-computed embeddings');
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

  // Fallback: keyword-based search using org descriptions from the GeoJSON data
  console.warn('[search] WARNING: Both ML methods failed, falling back to keyword search');
  console.log('[search] Using keyword-based fallback search');
  return await keywordSearch(query, topK);
}

/**
 * Keyword-based search fallback - works without any ML model.
 * Uses simple text matching against org names and descriptions.
 */
async function keywordSearch(query, topK = 200) {
  // Get org data from the global allOrganizations array
  const orgs = window.allOrganizations || [];
  if (orgs.length === 0) {
    console.error('[search] No org data available for keyword search');
    return [];
  }

  // Normalize query into keywords
  const queryLower = query.toLowerCase();
  const queryWords = queryLower.split(/\s+/).filter(w => w.length > 2);

  // Score each org
  const scored = orgs.map(org => {
    const name = (org.name || '').toLowerCase();
    const desc = (org.description || '').toLowerCase();
    const country = (org.country || '').toLowerCase();
    const searchText = name + ' ' + desc + ' ' + country;

    let score = 0;
    // Exact phrase match bonus
    if (searchText.includes(queryLower)) score += 10;

    // Individual word matches
    for (const word of queryWords) {
      if (name.includes(word)) score += 3;
      if (desc.includes(word)) score += 1;
      if (country.includes(word)) score += 2;
    }

    // Feature bonuses
    if (queryLower.includes('volunteer') && org.hasJobs) score += 2;
    if (queryLower.includes('stay') && org.hasStays) score += 2;
    if (queryLower.includes('event') && org.hasEvents) score += 2;
    if (queryLower.includes('job') && org.hasJobs) score += 2;

    return { id: org.id, score, lat: org.latitude, lon: org.longitude };
  });

  // Filter to orgs with score > 0, sort by score
  const results = scored
    .filter(r => r.score > 0)
    .sort((a, b) => b.score - a.score)
    .slice(0, topK)
    .map((r, i) => ({
      id: r.id,
      score: r.score / 20, // normalize roughly to 0-1 range
      rank: i + 1,
      lat: r.lat,
      lon: r.lon,
    }));

  return results;
}

window.loadEmbeddingIndex = loadEmbeddingIndex;
window.initWebLLMEngine = initWebLLMEngine;
window.initTransformers = initTransformers;
window.searchEmbeddings = searchEmbeddings;
