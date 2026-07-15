# Tidal Memory

A quiet, layered memory engine for conversational agents.

It remembers nearby conversations as impressions, preserves exact details out
of sight, and retrieves those details only when the recall policy permits.
There is no memory dashboard. Memory should flow, not become homework.

## What makes it different

- **Two resolutions:** low-resolution continuity and high-resolution detail
  never share the same injection path.
- **Stable identity memory:** core and high-importance semantic facts have a
  small, bounded opening block separate from both impressions and recall.
- **Progressive forgetting:** window impressions become weekly impressions,
  then monthly impressions. Source rows are archived, not destroyed.
- **A three-valve recall policy:** trigger sensitivity, association radius, and
  injection budget are independent controls.
- **Vector optional:** SQLite FTS5 plus multilingual lexical overlap works out
  of the box. Any vector retriever can be added behind one small interface.
- **Time-aware facts:** occurrence time and recording time are separate; old
  facts can be superseded without erasing their history.
- **No UI:** applications integrate the library or CLI. Debugging remains an
  engineering concern instead of a daily chore for the person chatting.

## Trial status

This is a small, framework-agnostic preview of the architecture. It deliberately
contains no data, prompts, credentials, or code copied from a private chat
deployment.

The offline impression writer is intentionally simple. For production, pass an
LLM callback that generates deliberately vague impressions. The store,
retrieval policy, context budgets, versioning, and rollup work without an LLM.

## Quick start

    python -m venv .venv
    . .venv/bin/activate
    pip install -e .
    tidal-memory --db demo.db demo

Manual use:

    tidal-memory --db demo.db remember \
      "Rin prefers jasmine tea to coffee." --layer semantic --importance 6

    tidal-memory --db demo.db impression chat-001 \
      "They talked about rainy walks; the mood was easy and affectionate."

    tidal-memory --db demo.db context --conversation-id chat-002
    tidal-memory --db demo.db recall --force \
      "Do you remember what Rin likes to drink?"

The complete integration pattern is in examples/chat_integration.py.

## Let your coding agent install it

Most people do not need to wire the hooks by hand. Give this repository to the
coding agent that maintains your chat application and send it this instruction:

> Read `AI_INTEGRATION.md`, inspect my current chat application, and integrate
> Tidal Memory in shadow mode first. Do not delete, overwrite, or migrate my
> existing conversations or memories. Back up every file and database you need
> to change, run the required tests, and show me the recall test results before
> enabling memory injection.

[`AI_INTEGRATION.md`](AI_INTEGRATION.md) tells the agent how to locate the three
integration hooks, preserve edits and regenerated branches, avoid prompt-cache
churn, validate recall quality, and produce a rollback-ready handoff report.

## The two paths

    window closes -> vague impression -> recent windows -> weekly -> monthly
                                                 |
    new window ----------------------------------+-> bounded background

    explicit/contextual reference -> retriever(s) -> verifier -> exact detail

Background types (window impression, weekly rollup, and monthly rollup) are
excluded from detail retrieval at the retriever boundary. They cannot consume
detail candidate slots.

## Recall policy

    from tidal_memory import RecallPolicy

    policy = RecallPolicy(
        trigger="balanced",                 # explicit | balanced | active
        association="direct_plus_one_hop",  # direct | direct_plus_one_hop
        max_items=2,
        max_chars=900,
        repeat_cooldown_turns=3,
        candidate_pool=8,
    )

Search can be broad; injection stays strict. A production integration may pass
a relevance verifier callback to TidalMemory for final candidate review.

## Bring your own retriever

Implement one method:

    from tidal_memory import Retriever, RetrievalHit

    class MyVectorRetriever(Retriever):
        def retrieve(self, query, *, limit=8, exclude_event_types=()):
            # Return RetrievalHit(memory, score, source="my-vector")
            ...

Combine it with the zero-dependency backend:

    from tidal_memory import HybridRetriever, KeywordRetriever, TidalMemory

    memory = TidalMemory("memory.db")
    memory.retriever = HybridRetriever(
        KeywordRetriever(memory.store),
        MyVectorRetriever(...),
    )

The embedding provider, dimensions, index, and score scale are not part of the
memory model.

## Bring your own impression writer

    def vague_writer(messages):
        # Call any model. Keep only broad topics and relational atmosphere.
        return "They spent the evening fixing things and teasing each other."

    memory = TidalMemory("memory.db", impression_writer=vague_writer)

The writer should remove exact numbers, quotations, tool names, instructions,
and intimate detail. It may retain at most one clearly unresolved direction.

For automatic durable facts, pass a fact_extractor callback. It receives the
window messages and returns dictionaries accepted by remember:

    def extract_facts(messages):
        return [{
            "summary": "Rin prefers jasmine tea.",
            "layer": "semantic",
            "importance": 6,
            "tags": "preference,drink",
        }]

    memory = TidalMemory("memory.db", fact_extractor=extract_facts)

## Natural-language controls

The library exposes primitives so a chat agent can map ordinary phrases:

- “Remember this” calls remember.
- “Forget that” calls forget.
- “My preference changed” calls store.supersede.
- “Why did you remember this?” can show retrieval hit provenance.

Applications can connect exact memories with store.link. The one-hop association
policy follows those edges after a direct match; background impressions remain
excluded even when linked.

No end-user management screen is required.

## Privacy boundary

Do not commit a live database. The default gitignore excludes SQLite files and
environment files. Applications should also:

- encrypt or protect the database at rest;
- require explicit export and delete controls;
- avoid storing secrets in memories;
- keep exact intimate details out of background impressions;
- log source IDs and policy decisions without logging private content.

## Tests

    python -m unittest discover -s tests -v

The suite checks path separation, Chinese lexical recall, recall triggers,
cooldown, fact supersession, rollup, and context budgets.

## License

Apache-2.0. Use it, modify it, teach another agent to install it, and share
what you learn.
