- README: "How it works" opens with a layered sketch of where Chock sits: you, a coding agent's generic parts
  (model, agent loop, context, hook point, tools), and your repository and pipeline, with Chock's nine points of contact
  (session start, the rules block, before and after a tool, end of the turn, the MCP gateway, `git commit`, `git push`,
  CI), each with its scope, and five things it stops. A test derives the list from the engine and fails when a hook is
  added without the figure.
  No prose was added: the README stays at its word budget. The figure is `docs/assets/readme/v2/where-chock-sits.png`,
  rendered by `render.mjs` from `where-chock-sits.json`; `docs/architecture.md` shows it above the
  author-compile-enforce figure.
