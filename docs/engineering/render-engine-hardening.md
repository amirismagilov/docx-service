# Render Engine Hardening Plan (DOCX v1)

## Objectives
- Keep generation reliable for large templates (100+ pages, dense conditionals).
- Achieve sync path P95 under 1 second for agreed profile.
- Shift heavy operations away from API request thread.
- Make render behavior deterministic and testable.

## Current Bottlenecks (from codebase)
- Repeated replacement probes during conditional target resolution.
- Full OOXML archive traversal for some fallback removals.
- In-process queue and worker contention with API thread.
- No reusable compiled template representation.

## Target Render Pipeline
1. **Template preparation (publish time)**
   - Parse DOCX once.
   - Build compiled index:
     - placeholder anchors,
     - conditional block anchors,
     - signature slot anchors.
   - Store compiled metadata in DB/cache.

2. **Generation execution (runtime)**
   - Validate payload by version schema.
   - Load compiled template metadata.
   - Resolve condition matrix once.
   - Apply replacements in single pass over indexed anchors where possible.
   - Apply signatures with bounded operations.
   - Emit generated DOCX + result metadata (checksum, size, timings).

3. **Async heavy path**
   - Large template or high-complexity requests routed to worker queue.
   - API returns accepted response with job status URL.

## Refactoring Workstreams

### WS1: Engine modularization
- Extract rendering concerns into explicit services:
  - `TemplateCompilerService`
  - `ConditionalResolverService`
  - `DocxMutationService`
  - `SignaturePlacementService`
  - `GenerationOrchestratorService`
- Introduce typed DTOs and deterministic return model.

### WS2: Anchor indexing and caching
- Generate stable anchor IDs at publish time.
- Persist anchor map in PostgreSQL JSONB and cache hot versions in Redis.
- Cache key: `template:{versionId}:compiled:v{compilerVersion}`.

### WS3: Conditional block optimization
- Precompute candidate spans and occurrence maps during compile.
- Replace repeated trial-replace loops with direct index-based mutation.
- Preserve correctness on multiline and split-run structures.

### WS4: Signature insertion
- Define slot model (`anchorText`, `occurrenceIndex`, offsets, dimensions).
- Validate image formats and dimensions before runtime.
- Bound image insertion failures to slot-level errors with policy (`fail-fast`/`skip`).

### WS5: Performance guardrails
- Complexity scoring before execution:
  - pages estimate,
  - condition count,
  - placeholder count,
  - table density.
- Route strategy:
  - `sync-fast` for low complexity,
  - `async-heavy` for high complexity.

## Benchmark Program

## Corpus
- `S`: 10-20 pages, <= 100 placeholders, <= 30 conditions.
- `M`: 30-60 pages, <= 300 placeholders, <= 120 conditions.
- `L`: 100-150 pages, <= 800 placeholders, <= 400 conditions.

## Metrics
- Latency: P50/P95/P99 by profile and mode.
- Throughput: docs/min sustained and burst.
- Memory peak per worker.
- Error rate by error class.
- Queue wait time (async).

## Test Protocol
- Warm-up stage for caches.
- 15-minute sustained run + burst windows.
- Re-run after each optimization milestone.
- Fail CI on regression beyond threshold:
  - +15% P95 latency,
  - +20% memory,
  - any correctness drift in golden outputs.

## Milestones
1. **M1 (1 week)**: service extraction + compatibility shim.
2. **M2 (1-2 weeks)**: compiler/indexing and cache integration.
3. **M3 (1 week)**: optimized conditional and signature paths.
4. **M4 (1 week)**: benchmark hardening and CI performance gates.

## Rollout Strategy
- Shadow mode: old and new engine run in parallel on sample traffic.
- Diff validator compares binary-normalized outputs and semantic text.
- Canary by tenant/document subset.
- Full cutover only after SLO and correctness acceptance.

## Done Criteria
- Sync fast profile P95 < 1s in staging benchmark.
- Large profile stable in async with bounded queue delay.
- No correctness regressions on golden corpus.
- Full instrumentation of stage timings and failure reasons.
