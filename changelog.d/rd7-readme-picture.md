- README: "How it works" opens with a picture of a coding agent's harness: component cards in layers (input, core,
  execution) with short arrows between neighbours, beside the repository and pipeline. The hooks of each component
  are badges on its card: filled where Chock runs today, hollow where a policy of your own can run; the model has
  none. No prose was added: the README stays at its budgets. The figure is `docs/assets/readme/v2/where-chock-sits.png`,
  rendered by `render.mjs` and `where-chock-sits.mjs` from `where-chock-sits.json`. `docs/architecture.md` shows it,
  lists every hook, and shows the same points in session order (`v2/session-path.png`). Tests assert the badges equal
  agentseam's events plus the other points, the filled set equals what the engine handles, and that no two shapes of
  either layout are too close.
