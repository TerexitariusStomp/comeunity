import { pipeline, env } from '@xenova/transformers';

env.allowLocalModels = false;
env.useBrowserCache = true;

const modelId = 'Xenova/all-MiniLM-L6-v2';
const query = 'permaculture community accepting volunteers in Europe';

const extractor = await pipeline('feature-extraction', modelId);
const output = await extractor(query, { pooling: 'mean', normalize: true });
const queryVec = Array.from(output.data);
console.log(`queryVec length=${queryVec.length}`);

const metaPath = new URL('../data/embeddings-meta.json', import.meta.url).href;
const meta = await (await fetch(metaPath)).json();

const idx = (meta.count < 500 ? meta.count : 500);
console.log(`loaded metadata for ${meta.count} embeddings, will score ${idx}`);

const scores = [];
let best = { score: -Infinity, id: null };
let worst = { score: Infinity, id: null };
for (let i = 0; i < idx; i++) {
  const item = meta.embeddings[i];
  const blob = new Uint8Array(Buffer.from(item.e, 'base64'));
  const scale = (meta.range[1] - meta.range[0]) / 255;
  let dot = 0;
  for (let j = 0; j < queryVec.length; j++) {
    const v = queryVec[j];
    const b = blob[j] * scale + meta.range[0];
    dot += v * b;
  }
  scores.push({ score: dot, id: item.id });
  if (dot > best.score) best = { score: dot, id: item.id };
  if (dot < worst.score) worst = { score: dot, id: item.id };
}

scores.sort((a, b) => b.score - a.score);
console.log(`best=${JSON.stringify(best)}`);
console.log(`worst=${JSON.stringify(worst)}`);
console.log(`top5=${JSON.stringify(scores.slice(0, 5))}`);
