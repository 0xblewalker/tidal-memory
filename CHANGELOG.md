# Changelog

## 0.1.0 - Trial preview

- SQLite memory store with separate occurrence and recording times.
- Core, semantic, episodic, procedural, and impression-compatible layers.
- Window, weekly, and monthly impression ladder with bounded context.
- Bounded stable context for core and high-importance semantic memories.
- Optional automatic fact-extractor callback at window close.
- Exact-detail recall isolated from all background impression types.
- Three-part recall policy: trigger, association radius, and injection budget.
- SQLite FTS5 plus multilingual lexical retrieval with no vector dependency.
- Pluggable retriever, vector, impression-writer, and relevance-verifier APIs.
- One-hop memory relations and reciprocal-rank hybrid retrieval.
- Fact supersession, soft forgetting, repeat cooldown, and provenance.
- CLI, framework-neutral integration example, privacy guidance, and tests.
- No end-user memory dashboard.
