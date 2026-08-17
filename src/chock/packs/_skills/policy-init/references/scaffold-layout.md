# Scaffold layout by artifact class

`policy-init` creates the full folder structure for every artifact. Placeholder files are allowed during scaffolding and must be marked with `<!-- SCAFFOLD: replace or delete before review -->`.

## skill

```text<id>/
├── manifest.yaml
├── SKILL.md
├── evals/
│   └── suite.yaml
├── examples/
│   └── README.md
└── assets/
    └── .gitkeep
```

## code / hybrid skill

Same as skill plus:

```text├── scripts/
│   ├── README.md
│   └── <entrypoint>.py
```

## hook

```text<id>/
├── manifest.yaml          # contains hook.gate
├── evals/
│   └── suite.yaml
├── implementations/       # only when the hook needs a script
│   └── <gate>.sh
└── references/
```

## rule

```text<id>/
├── manifest.yaml
├── evals/
│   └── suite.yaml
└── references/
```

## subagent

```text<id>/
├── subagent.yaml
├── evals/
│   └── suite.yaml
└── references/
```

## multi-agent workflow / orchestrator

See `references/multi-agent-scaffold.md`.
