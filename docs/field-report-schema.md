# Field Report Schema

KnowField is designed around a field-level report rather than a single-paper summary.

The target report answers:

1. What is this field in plain language?
2. Why did it appear?
3. How did it develop?
4. What stage is it currently in?
5. What are people working on now?
6. What has already become mature?
7. What remains difficult or unsolved?
8. Who are the important players?
9. How can a beginner go deeper?
10. What starter projects can turn curiosity into practice?

The current machine-readable schema is exposed through:

```bash
knowfield schema
```

The first usable workflow is intentionally simple:

```bash
knowfield init "edge computing" -o edge_computing.json
knowfield map edge_computing.json
```

This creates a starter report that a reader can edit, verify, and improve with sources.

## Maturity Model

- `L1 概念期`: definitions are unstable and evidence is sparse.
- `L2 探索期`: papers and prototypes increase, but tasks and metrics are not yet settled.
- `L3 成长期`: surveys, benchmarks, open-source projects, and recurring community venues appear.
- `L4 落地期`: products, deployments, engineering constraints, and jobs become visible.
- `L5 成熟期`: infrastructure stabilizes and work shifts toward cost, safety, standards, and incremental optimization.
