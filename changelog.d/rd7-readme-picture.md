- README: "How it works" opens with a layered sketch of where Chock sits: you, a coding agent's generic parts
  (model, agent loop, context, hook point, tools), and your repository and pipeline, with Chock's four connectors
  (a rules block in context, the hook point where the agent has hooks, `git commit`, CI) and five things it stops.
  No prose was added: the README stays at its word budget. The figure is `docs/assets/readme/v2/where-chock-sits.png`,
  rendered by `render.mjs` from `where-chock-sits.json`; `docs/architecture.md` shows it above the
  author-compile-enforce figure.
