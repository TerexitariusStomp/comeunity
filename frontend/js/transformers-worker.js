import { pipeline, env } from '@xenova/transformers';

env.allowLocalModels = false;
env.useBrowserCache = true;

let extractor = null;

async function getFeatureExtractor() {
  if (!extractor) {
    extractor = await pipeline('feature-extraction', 'Xenova/all-MiniLM-L6-v2');
  }
  return extractor;
}

self.addEventListener('message', async (e) => {
  const { type, id, text } = e.data || {};
  try {
    if (type !== 'encode') {
      throw new Error(`unsupported message type: ${type}`);
    }

    if (!text || typeof text !== 'string') {
      throw new Error('empty query text');
    }

    const model = await getFeatureExtractor();
    const output = await model(text, {
      pooling: 'mean',
      normalize: true,
    });

    const vector = Array.from(output.data);
    self.postMessage({ type: 'encoded', id, vector });
  } catch (error) {
    self.postMessage({
      type: 'error',
      id,
      error: error?.message || String(error),
    });
  }
});