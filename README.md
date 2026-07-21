# Aigent

Re:Mind is organized as a monorepo:

- `services/ai`: emotion analysis models, the coarse-emotion inference API, and tests
- `services/backend`: the application backend
- `packages/contracts`: shared JSON Schema contracts

The six-class Transformer weights and generated training outputs are runtime
artifacts and are intentionally not committed. See
[`services/ai/docs/coarse_emotion_inference.md`](services/ai/docs/coarse_emotion_inference.md)
for local setup, artifact layouts, API behavior, and validation notes.
