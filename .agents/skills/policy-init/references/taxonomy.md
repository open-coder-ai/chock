# Taxonomy: classify before you generate

walk_in_order with request; announce classification + reasoning; request may be MIXED

## Decision tree

0. determinism_scan before the walk:
   - identify deterministic_parts (repeatable, mechanical, scriptable, verifiable)
   - identify judgment_parts (requires interpretation, context, trade-off reasoning)
   - if request is MIXED, announce split and route deterministic_parts to a code/hybrid skill with a committed script

1. if violation_must_be_impossible then
   - class: hook
   - enforcement: block
   - artifact: code
   - gate rejects action pre-execution
   - compile to at least git hook
   - ambient rule: one line pointing to compliant path

2. else if violation_detectable_after_fact AND must_correct then
   - class: hook
   - enforcement: verify
   - artifact: code
   - agent self-corrects from gate output

3. else if always_relevant_to_every_prompt AND expressible_in <=2_lines then
   - class: rule
   - line(s) in marked Chock ambient section
   - if >2 lines then reclassify as skill

4. else if repeatable_procedure_run_on_demand then
   - if entirely mechanical, no judgment → class: code skill with committed script
   - else if requires reasoning but follows a fixed procedure → class: skill
   - if orchestrates several skills then class: workflow skill

5. else if situational_knowledge_for_task_class then
   - class: skill
   - purely descriptive → skill_type: nl
   - mechanical check or generator script → skill_type: hybrid
   - entirely mechanical, no judgment → skill_type: code

6. else if scoped_single_purpose_reasoning_agent_invoked_by_workflow then
   - class: subagent
   - declare: purpose, input/output schema, `bounded_to` tool scope, `max_iterations`

7. else if multi_step_workflow_coordinating_skills_subagents then
   - user-facing label: multi-agent workflow / orchestrator
   - internal class: workflow skill
   - describe the ordered procedure in SKILL.md and declare dependencies in manifest.yaml

## Guardrails

- stakes_rule: security/compliance stakes force verify or block; if developer asks advise-level for stakes policy, push back once, explain mismatch, record decision in manifest changelog if they insist
- effects_rule: if any declared effect is `writes_external` or `irreversible`, enforcement must be `verify` or `block` and approval wiring must be included
- never_dead-end: if request is not skill-shaped, generate the artifact it IS shaped as
- pre-generated_scripts: every script must be committed under a code/hybrid skill and invoked by that skill; do not leave an ad-hoc script uncommitted or generate one at runtime
- capability_boundaries (tools/servers agent may use) are agent permission configuration, not Chock artifacts; point developer at agent settings and stop
- workflow_skills_are_agent_driven: a workflow skill sequences agent invocations; there is no headless workflow engine
- determinism_scan: a mixed request must not bury its deterministic half in prose inside an NL skill; mechanical parts become a code/hybrid skill with a committed script
