# Template: scripts/README.md

This folder contains deterministic scripts invoked by the skill.

Rules:

- No LLM calls inside scripts.
- No network calls unless the skill declares a `network` effect with approval.
- No plaintext secrets.
- Scripts must be committed; never generated at runtime.

<!-- SCAFFOLD: replace or delete before review -->
