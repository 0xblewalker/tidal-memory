# AI Integration Guide

This document is written for the coding agent that will integrate Tidal Memory
into an existing conversational application.

Your job is to give the host agent layered, bounded memory without replacing
its current chat history or changing its personality. Inspect the host project
before editing it. Preserve its conventions, storage model, streaming path,
and deployment workflow.

## Human handoff prompt

The person installing this project can give you this instruction:

> Read `AI_INTEGRATION.md`, inspect my current chat application, and integrate
> Tidal Memory in shadow mode first. Do not delete, overwrite, or migrate my
> existing conversations or memories. Back up every file and database you need
> to change, run the required tests, and show me the recall test results before
> enabling memory injection.

## Non-negotiable invariants

1. Existing chat messages remain the source of truth. Tidal Memory is a derived
   index, not a replacement conversation store.
2. Never commit or print private memory content, credentials, or a live SQLite
   database.
3. Impressions and exact details use different injection paths. Do not return
   `window_impression`, `rollup_week`, or `rollup_month` from detail retrieval.
4. Keep injection bounded. More retrieved text is not better memory.
5. Store occurrence time separately from recording time. Do not infer an event
   date from the time it was extracted.
6. Editing or regenerating a branch must not leave abandoned assistant replies
   in the active window or generate duplicate impressions.
7. Do not change the agent's identity, voice, relationship style, or safety
   policy as part of this integration.

## Phase 1: map the host application

Locate and document these points before making edits:

- the canonical conversation and message tables;
- conversation/window identifiers and branch semantics;
- the function that assembles model messages;
- the user-message send path and streaming completion path;
- new-window, edit, regenerate, delete, and hard-reset behavior;
- the place where a window can be considered inactive or closed;
- background-job or scheduler support;
- existing memory, search, embedding, cache, and prompt-injection code;
- deployment, restart, health-check, test, and rollback commands.

If the application already has memory, do not silently replace it. Add an
adapter or run both systems in shadow mode until their behavior is compared.

## Phase 2: install and initialize

From this repository:

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e .
python -m unittest discover -s tests -v
```

Create one `TidalMemory` instance per process, pointed at a protected database
outside the repository. Close it during graceful shutdown.

```python
from tidal_memory import RecallPolicy, TidalMemory

memory = TidalMemory(
    "/protected/path/tidal-memory.db",
    policy=RecallPolicy(
        trigger="balanced",
        association="direct_plus_one_hop",
        max_items=2,
        max_chars=900,
        repeat_cooldown_turns=3,
        candidate_pool=8,
    ),
    impression_writer=write_vague_impression,
    fact_extractor=extract_durable_facts,
    relevance_verifier=verify_relevance,
)
```

The callbacks may call the host application's existing model provider. Keep
them optional so chat still works if memory processing fails.

## Phase 3: connect the three hooks

### A. Opening context

On the first model request of a new conversation window, call:

```python
opening = memory.opening_context(conversation_id)
```

Insert the result in a clearly delimited system/developer context block. Inject
it once per window, before the current conversation, and never append it to the
visible user message or persist it as chat history.

```text
<memory_context source="tidal:opening" resolution="low">
...
</memory_context>
```

This block contains bounded stable memory and deliberately vague impressions.
It provides continuity, not evidence for exact claims.

### B. Detail recall

Before each model request, call:

```python
detail = memory.recall(current_user_text)
```

When non-empty, add it as a separate, ephemeral context block immediately
before the current user message:

```text
<memory_context source="tidal:recall" resolution="exact">
...
</memory_context>
```

Do not write this block into the canonical chat transcript. Do not let recalled
text replace the current user's words. Treat it as fallible historical context,
especially when facts conflict with a newer user statement.

### C. Window close

After a window is genuinely closed or inactive, pass only the active branch's
user and assistant messages:

```python
memory.close_window(
    conversation_id,
    active_messages,
    title=conversation_title,
    occurred_at=window_start_or_best_known_event_time,
)
```

Make this job idempotent by conversation ID. Debounce it so a transient
disconnect, page close, or stream retry does not produce multiple summaries.
Do not treat every HTTP request as a window close.

## Callback contracts

### Impression writer

Return two or three short sentences about broad topics, relational atmosphere,
and at most one unresolved direction. Deliberately omit:

- exact numbers and timestamps;
- quotations and message-by-message narration;
- secrets, intimate specifics, and identifying data;
- tool calls, implementation details, and safety incidents;
- speculative personality diagnoses.

An impression should sound like “they spent the evening fixing something and
teasing each other; the mood was warm,” not a compressed transcript.

### Fact extractor

Save only facts likely to matter in a later window: stable preferences,
relationships, commitments, durable project state, and meaningful changes.
Return dictionaries accepted by `TidalMemory.remember`.

Do not promote jokes, one-off moods, model guesses, recalled text, tool output,
or the assistant's own claims. When a fact changes, supersede the old row rather
than deleting history.

### Relevance verifier

Receive the current query and retrieval candidates. Remove candidates that are
merely lexically similar, stale, contradictory, overly intimate for the current
topic, or unnecessary to answer the current message. Preserve ordering only
among the candidates that remain useful.

## Shadow mode

Implement a feature flag such as `TIDAL_MEMORY_INJECT=0`.

With injection disabled:

- write impressions and durable facts to a fresh database;
- run recall decisions and record only IDs, scores, provenance, character
  counts, and the reason for injection or suppression;
- never log the private memory text itself;
- compare results with the host's existing memory system;
- expose a developer-only diagnostic command or report.

Enable injection only after the human reviews representative cases.

## Editing, regeneration, and branching

The model request must be assembled from the active branch each time. When a
user edits an earlier message or regenerates an answer:

- exclude superseded messages and abandoned replies from model context;
- do not call `close_window` for the discarded branch;
- invalidate any pending impression job for the old branch;
- do not duplicate already stored durable facts;
- keep injected memory ephemeral so editing cannot bake it into chat history.

If the host supports both “edit with history” and “hard rewrite,” preserve that
distinction. A hard rewrite should behave like the replaced branch never became
part of the active conversation, while audit/history behavior remains a host
application decision.

## Rollups and maintenance

Run `memory.rollup()` from a server-side scheduled job, not from the browser.
Daily is sufficient. It archives source impressions after producing weekly or
monthly summaries; it does not delete the originals.

Back up the SQLite database before schema changes. Use a single-writer strategy
or the host application's job queue if several processes may perform extraction
or rollups concurrently.

## Cache behavior

Memory context affects the model prompt prefix and therefore prompt-cache
identity. Keep the stable opening block ordered and deterministic. Do not add
volatile timestamps, debug counters, random IDs, or changing status text to the
cached prefix. Put per-turn recalled detail after the stable prefix.

Do not keep a provider cache alive solely from a browser timer. If the host uses
cache heartbeats, own them server-side and treat them as a separate optimization
from memory correctness.

## Required verification

Before enabling injection, demonstrate all of the following:

1. A new window receives a vague recent impression, not a transcript.
2. Ordinary small talk does not retrieve an unrelated old event.
3. An explicit “do you remember…” query retrieves the relevant exact detail.
4. The same detail respects repeat cooldown and the character/item budget.
5. A changed preference supersedes the old fact without erasing its history.
6. An edited/regenerated branch does not leak an abandoned reply.
7. A closed window creates at most one impression.
8. Weekly/monthly rollups leave the opening context bounded.
9. Failure of extraction, recall, or the memory database does not prevent chat.
10. Existing conversations and existing memory data remain unchanged.

Run the library suite plus host-project tests, then perform one cold-start chat,
one explicit recall chat, and one edit/regenerate flow through the real API.

## Handoff report

Give the human a short report containing:

- files and database schema changed;
- backup and rollback location;
- the three hook locations;
- callback models/providers used and estimated background cost;
- shadow-mode observations and false-positive examples;
- test commands and results;
- feature flag and how to disable the integration instantly;
- unresolved risks or assumptions.

Do not claim the integration is complete merely because the package imports.
It is complete when the active production request path has been exercised and
the human has seen evidence that remembering and not remembering both work.
