const { pipeline, env } = await import('https://cdn.jsdelivr.net/npm/@xenova/transformers@2.17.2');

let featureExtractor = null;

env.allowLocalModels = false;

async function getFeatureExtractor() {
    if (featureExtractor) return featureExtractor;
    featureExtractor = await pipeline('feature-extraction', 'Xenova/all-MiniLM-L6-v2');
    return featureExtractor;
}

self.addEventListener('message', async (e) => {
    try {
        const { type, id, value } = e.data || {};

        if (type === 'init') {
            await getFeatureExtractor();
            self.postMessage({ type: 'ready', id });
            return;
        }

        if (type === 'encode') {
            if (!featureExtractor) {
                throw new Error('Feature extractor not ready');
            }

            const output = await featureExtractor(value, { pooling: 'mean', normalize: true });
            const vector = Array.from(output.data);
            self.postMessage({ type: 'encoded', id, value: vector });
            return;
        }

        self.postMessage({ type: 'error', id, error: `Unknown message type: ${type}` });
    } catch (error) {
        self.postMessage({ type: 'error', id, error: error && error.message ? error.message : String(error) });
    }
});