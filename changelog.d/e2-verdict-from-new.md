- A script gate's finding may carry a `tier` (`block`, `ask` or `warn`). When every finding the change adds carries
  one, the verdict is the highest tier among them, so an old block-tier finding in a touched file no longer turns a
  new ask-tier finding into a block. A script that reports no tier, or tiers only some findings, keeps its exit code
  as the verdict, as before. See `spec/gate-dsl.md`.
