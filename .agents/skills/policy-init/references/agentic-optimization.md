# Agentic optimization patterns

When `policy-init` generates a skill, subagent, or workflow skill, apply these patterns by default. These are derived from production practices across major open-source agentic frameworks (MemGPT/Letta, CrewAI, LangChain/LangGraph, AutoGen, SWE-agent, OpenHands, DSPy).

## Token optimization

### Output capping

Cap tool output to prevent context flooding. A single uncapped command can inject 50K+ tokens.

- Shell output: `head -c 4000` (byte-cap, not line-cap — single long lines bypass `head -n`)
- Search results: return top 3-4, not all matches
- File reads: targeted line ranges, not full files
- Log tailing: `tail -c 4000` for recent output

### Bounded iteration

Uncapped retry loops cause quadratic token growth (a 10-cycle loop consumes ~50x a single pass).

- Hard cap: max 3 retries before diagnosing root cause
- Exit condition: stop if 2 consecutive iterations show no measurable improvement
- Escalation: after cap, surface the failure — don't silently retry

### On-demand reference loading

Load references only when the current step requires them (progressive disclosure). At startup, load only names + one-line descriptions (~80 tokens each). Full bodies (275-8000 tokens) load on trigger.

- Skill files: activation surface in SKILL.md; depth in `references/`
- Tool schemas: load only tools relevant to current phase
- Documentation: fetch specific sections, not entire docs

### Structured output preference

Structured output (JSON, YAML, tables) is 30-60% more token-efficient than prose for the same information density. Prefer schemas, pseudocode, and command formats over natural language.

### Conversation deduplication

Never re-read a file that is already in context and unchanged. Track file-read history; replace repeated reads with "file already in context" notice. After writing a file, retain the path reference — not the full content — in conversation history.

## Context management

### Three-layer working memory

Organize runtime context into three layers with distinct lifetimes:

| Layer | Contains | Lifetime | Size |
|---|---|---|---|
| Working state | Current objective, constraints, active tool results | Single turn | Constant |
| Session summary | Decisions made, dead ends explored, findings | Checkpoint-based | Grows, then compacts |
| Long-term facts | User preferences, project conventions, reusable patterns | Cross-session | Query on demand |

Working state is always in context. Session summary compacts at checkpoints. Long-term facts load only when relevant.

### Observation masking

Replace old environment observations (command outputs, file contents, error traces) with short placeholders while preserving the agent's own reasoning steps. SWE-agent found this reduces costs by 50% with 2.6% higher solve rates than LLM summarization.

Pattern: after resolving an issue, replace the full error trace + investigation with:
```
[resolved: auth middleware was missing token refresh — fixed in auth.py:42]
```

### Subagent delegation for noisy exploration

Keep exploratory/investigative work outside the main context. Subagents read files independently and return only a compressed summary. Benchmark: 6,100 tokens read by subagent → 420-token summary returned (93% reduction).

Use subagent delegation when:
- Searching across >3 files for a symbol or pattern
- Investigating a bug with multiple hypotheses
- Reviewing code that won't be edited

### Context budget awareness

Performance degrades measurably when context exceeds 50% utilization (even with 200K windows). At 25% full, some models already show degradation.

- Monitor context growth; summarize when approaching 40% utilization
- After each phase in a multi-step task, compact prior phase to findings-only
- Prefer re-reading files over carrying their content across turns

## Context rot prevention

### What context rot is

Context rot is the measurable degradation in LLM performance as input context grows with stale, irrelevant, or contradictory information. Proven across 18 models by Chroma research (2025). Even well within window limits, accumulated noise degrades accuracy.

### Staleness detection

Content becomes stale when:
- A file was read >3 turns ago and may have been modified since
- An error trace belongs to a bug that's already fixed
- A design decision has been superseded by a later decision
- Tool output from an abandoned approach is still in context

### Prevention strategies

1. **Path refs over content**: After writing or reading a large file, retain only the path. The agent can re-read if needed.
2. **Prune resolved content**: Once a bug is fixed, replace the investigation trace with a one-line resolution summary.
3. **Supersede, don't accumulate**: When a decision changes, remove the old decision context — don't keep both.
4. **Checkpoint compaction**: At natural breakpoints (phase transitions, task completion), summarize everything before the checkpoint into a compact summary.
5. **Fresh reads over stale cache**: When acting on file content, re-read if the content is >3 turns old. Files change.

### GSD cycle (Gather → Summarize → Dispatch)

For long-running tasks, run this cycle periodically:
1. **Gather**: Collect all context needed for the next step
2. **Summarize**: Compress prior work into findings + decisions
3. **Dispatch**: Execute the next step with fresh, focused context

## Memory management

### What to persist (cross-session)

| Persist | Don't persist |
|---|---|
| Design decisions + reasoning | File contents (re-read instead) |
| User preferences + conventions | Git history (use git log) |
| Non-obvious constraints | Debugging steps (fix is in code) |
| Architecture choices | Task intermediates |
| Corrections / feedback | Ephemeral state |

### Atomic fact extraction

Never persist large blobs. Extract discrete atomic facts before storing. Each fact should be independently retrievable and useful.

Bad: "The authentication system uses JWT tokens stored in httpOnly cookies with a 24-hour expiry and refresh tokens stored in Redis with a 7-day TTL."

Good: Three separate facts:
- Auth uses JWT in httpOnly cookies (24h expiry)
- Refresh tokens stored in Redis (7-day TTL)
- Cookie-based auth, not header-based

### Consolidation

Before storing a new memory, check for existing similar memories (similarity > 0.85). Update the existing memory rather than creating a duplicate. This prevents unbounded memory growth.

### Decay and verification

Memories decay in relevance over time. Before recommending based on a memory:
- If it names a file path: verify the file exists
- If it names a function or flag: grep for it
- If the user is about to act on it: verify first

"The memory says X exists" is not the same as "X exists now."

### Three-tier taxonomy

Organize persistent memory into three tiers (from cognitive science, adopted by LangMem SDK, CrewAI):

| Tier | What | Retention |
|---|---|---|
| Episodic | Specific interaction events, corrections | Decays with time; prunable |
| Semantic | Extracted facts, decisions, preferences | Long-lived; update on contradiction |
| Procedural | Learned workflows, successful patterns | Stable; version on change |
