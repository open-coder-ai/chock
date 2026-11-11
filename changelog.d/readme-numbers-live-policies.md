- **README numbers leave out deprecated policies.** `docs/assets/readme/derive.py` skips a registry
  entry whose `status` is `deprecated`, so the README counts what chock.sh lists. At catalog
  `1e60d21`: 71 policies (was 72), 11 in the agent (was 12), 38 Claude Code `block` labels (was 39),
  4,390 of 4,572 eval cases replayed (was 4,501 of 4,683).
