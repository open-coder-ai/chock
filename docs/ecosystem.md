# The open-coder-ai family

chock is one of several repositories under [open-coder-ai](https://github.com/open-coder-ai), all built on one rule: a
claim must match a mechanism. This page says what each sibling is and how chock relates to it.

| Repository | What it is |
| :--- | :--- |
| [chock-catalog](https://github.com/open-coder-ai/chock-catalog) | The policies, each graded by what it actually enforces. chock ships mechanism only and bundles no policies; the catalog is where `chock add` reads from |
| [agentseam](https://github.com/open-coder-ai/agentseam) | The primitives layer for every coding agent: one handler API over their hooks, instruction files, plugin packaging and config, with a capability matrix that carries its provenance. chock is one thing built on it |
| [context-report](https://github.com/open-coder-ai/context-report) | A signed report format for whether a plugin, hook, skill or `AGENTS.md` actually works; chock can export one |
| [chock-threat-intel](https://github.com/open-coder-ai/chock-threat-intel) | A weekly, human-reviewed digest of agentic-AI threats scored against the catalog: enforced, advisory, or `policy wanted`. Feeds the roadmap |
| Plugins | Two routes. The chock.sh builder produces one plugin for any client from a selection, via `chock install --selection <code> --apply` (see [agent plugins](agent-plugins.md#the-hook-carrying-vendor-formats)). For machines that cannot install chock, the five `chock-*-plugins` repos stay as a per-policy marketplace, republished with every chock release; use one route per policy, never both. |
| [chock-quickstart](https://github.com/open-coder-ai/chock-quickstart) · [chock-example](https://github.com/open-coder-ai/chock-example) | Template repositories: exactly what `chock init` leaves behind, and a working adoption with one policy per layer |

Where a contribution goes:

- **A policy**, new or corrected — the catalog. It reaches every client from there,
  including the four plugin distributions, which close hand-written pull requests.
- **Evidence about what an agent actually does** — agentseam's evidence-report template.
  Most rows in its matrix rest on vendor documentation, and a live run that contradicts
  one is the most useful thing a contributor can send.
- **A gap between a published threat and the catalog** — a `policy wanted` entry in the
  threat ledger, linked to an issue to claim.
- **The framework itself** — here, per [CONTRIBUTING.md](../CONTRIBUTING.md).
