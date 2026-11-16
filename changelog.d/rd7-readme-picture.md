- README: "How it works" opens with a layered sketch of where Chock sits: you, a coding agent's generic parts
  (context, model, agent loop, tools, MCP servers, subagents) and your repository and pipeline. Every point
  agentseam exposes (`agentseam.contract.EVENTS`) is a marker where it happens; the ones Chock acts on today are
  filled and joined to the Chock box, the rest are hollow. No prose was added: the README stays at its budgets.
  The figure is `docs/assets/readme/v2/where-chock-sits.png`, rendered by `render.mjs` and `where-chock-sits.mjs`
  from `where-chock-sits.json`; `docs/architecture.md` lists every point under it. A test asserts the markers equal
  agentseam's events and the filled set equals what the engine handles.
