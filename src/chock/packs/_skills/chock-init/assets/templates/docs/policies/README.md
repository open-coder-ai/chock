# Policies

A policy is the umbrella term for rules, hooks, skills, workflows, and subagents.

## Artifacts

| Artifact | Lives in | Use case |
|---|---|---|
| rule | `.agents/policies/<id>/` | Ambient guidance |
| hook | `.agents/policies/<id>/` | Commit-time gate |
| skill | `.agents/skills/<id>/` | Reusable skill |
| subagent | `subagents/<id>/` | Scoped helper agent |

Note: the policy registry scans `.agents/policies/` and `.agents/skills/`; subagents are not registry-scanned today.

A skill with `artifact: workflow` sequences other skills/subagents via its `SKILL.md` procedure. A skill with `skill.skill_type: code` or `hybrid` may ship committed deterministic scripts under `scripts/` and invoke them from its procedure.

## Single-destination rule

Every policy lives in exactly one folder. Do not duplicate. Do not leave temporary files outside the deliverable folder.

## How to create a policy

Use the `policy-init` skill from the Chock framework repo. It classifies the request, interviews you, drafts evals, and scaffolds the folder.
