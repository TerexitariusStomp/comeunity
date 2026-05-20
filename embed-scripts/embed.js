/**
 * Pre-compute embeddings for all organizations using WebLLM.
 * Reads organizations.db, generates name+description embeddings via snowflake-arctic-embed-m,
 * and writes a compact JSON file with id, lat, lon, and embedding vector.
 *
 * Usage: node embed.js
 * Output: ../frontend/data/embeddings.json
 */
const webllm = require("@mlc-ai/web-llm");
const Database = require("better-sqlite3");
const fs = require("fs");
const path = require("path");

const DB_PATH = path.join(__dirname, "..", "backend", "organizations.db");
const OUT_PATH = path.join(__dirname, "..", "frontend", "data", "embeddings.json");
const BATCH_SIZE = 32; // snowflake-arctic-embed-m with b32 compilation

async function main() {
  // Read all organizations
  const db = new Database(DB_PATH, { readonly: true });
  const rows = db.prepare(`
    SELECT id, name, description, latitude, longitude
    FROM organizations
    WHERE latitude IS NOT NULL AND longitude IS NOT NULL
  `).all();
  db.close();

  console.log(`Loaded ${rows.length} organizations`);

  // Format texts for embedding
  const texts = rows.map(r => {
    const desc = (r.description || "").slice(0, 500); // cap description length
    return `${r.name}. ${desc}`;
  });

  // Initialize WebLLM embedding engine
  const modelId = "snowflake-arctic-embed-m-q0f32-MLC-b32";
  console.log(`Loading model: ${modelId}`);

  const engine = await webllm.CreateMLCEngine(modelId, {
    initProgressCallback: (report) => {
      process.stdout.write(`\r${report.text}`);
    },
    logLevel: "INFO",
  });
  console.log("\nModel loaded.");

  // Generate embeddings in batches
  const embeddings = [];
  const totalBatches = Math.ceil(texts.length / BATCH_SIZE);

  for (let i = 0; i < texts.length; i += BATCH_SIZE) {
    const batch = texts.slice(i, i + BATCH_SIZE);
    const batchNum = Math.floor(i / BATCH_SIZE) + 1;

    const reply = await engine.embeddings.create({ input: batch, model: modelId });

    for (let j = 0; j < batch.length; j++) {
      const row = rows[i + j];
      embeddings.push({
        id: row.id,
        lat: row.latitude,
        lon: row.longitude,
        e: reply.data[j].embedding,
      });
    }

    process.stdout.write(`\rBatch ${batchNum}/${totalBatches} (${embeddings.length}/${texts.length})`);
  }

  console.log(`\nGenerated ${embeddings.length} embeddings`);

  // Write compact output
  const output = {
    model: modelId,
    dim: embeddings[0].e.length,
    count: embeddings.length,
    embeddings: embeddings,
  };

  fs.mkdirSync(path.dirname(OUT_PATH), { recursive: true });
  fs.writeFileSync(OUT_PATH, JSON.stringify(output));

  const sizeMB = fs.statSync(OUT_PATH).size / (1024 * 1024);
  console.log(`Written to ${OUT_PATH} (${sizeMB.toFixed(1)} MB)`);

  // Cleanup
  engine.unload();
  process.exit(0);
}

main().catch(err => {
  console.error(err);
  process.exit(1);
});
