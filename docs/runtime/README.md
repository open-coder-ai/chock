# Workflow skills & script hygiene

Chock is an agents framework: every deliverable is agent-native. There is no headless runtime engine. Multi-step work is expressed as a **workflow skill** whose `SKILL.md` describes the ordered procedure the agent follows.

## Workflow skills

A workflow skill (`artifact: workflow`) coordinates other skills and subagents by describing:

1. The ordered steps.
2. The input passed to each step.
3. How to use the output of one step in the next.
4. The final output shape.

The agent itself performs the invocations; the manifest only declares dependencies and procedure.

## Script hygiene

Deterministic logic belongs in a committed script under a `code` or `hybrid` skill:

- Place the script under `<skill>/scripts/`.
- Declare `scripts.entrypoint` in `manifest.yaml`.
- In `SKILL.md`, instruct the agent to run the script with the required input.
- Never generate a script at runtime.
- Never ship a standalone script as a deliverable.

## Example

- A skill needing a structured rule set ships it under `assets/` and resolves it from its own
  location, so it works wherever it is installed.
