# Custom policies

Your own policies can join a selection beside catalog policies and be built into the same plugin, for any of the
five clients. Nobody but you has reviewed them, so install shows their code and asks before it builds them, and
every surface labels them **custom, not reviewed**.

## 1. Start from a template

```bash
chock new policy <id> --kind {content_regex|guard|script|rule|skill} [--root <folder>]
```

| Kind | What it does | Files besides `manifest.yaml` and `evals/suite.yaml` |
| :--- | :--- | :--- |
| `content_regex` | Refuses an added line matching a pattern, at commit and on the agent's writes | — |
| `guard` | Refuses or asks about a shell command before the agent runs it | `implementations/<id>.py` |
| `script` | Runs your script on the files a commit or write changes; its exit code decides | `implementations/check.py` |
| `rule` | Text the agent reads in its context; nothing enforces it | — |
| `skill` | A skill the agent loads when a request matches it | `skill/body.md` |

Outside a catalog (a folder with no `registry.yaml`) the id gains the reserved `my-` prefix, so it never collides
with a catalog id. The policy lands in `<folder>/.agents/policies/<id>/`. Each template validates and passes its own
evals as written; edit it, then check it:

```bash
chock check --repo <folder> --only validate,evals
```

A `rule`, `guard` or `skill` puts text in the agent's context, which SEC-5 allows below `trust_tier: community` only
with `ambient_override: true` and an `ambient_override_reason`. The templates set the reason to
"authored by the installing user".

## 2. Add it to a selection

A schema-2 selection names it with `from: local` and a path relative to the selection file's own folder:

```yaml
schema: 2
client: claude-code
bundle: {name: chock-guardrails, version: 1.0.0}
catalog: {source: https://github.com/open-coder-ai/chock-catalog, ref: <40-hex commit>}
policies:
  - {from: catalog, id: block-destructive-commands, version: <version>, sha256: <64-hex>}
  - {from: local, id: my-tf-destroy, path: .agents/policies/my-tf-destroy}
```

`sha256` is optional on a local entry; when present, the folder must hash to it. A selection with only local
entries needs no `catalog`. A link or a `#s=` code never carries a local policy: install refuses one, because only a
file has a folder beside it.

## 3. Install

```bash
chock install --selection <folder>/chock.selection.yaml [--client <agent>] [--trust-local <id>=<sha256>]
```

For each local entry, install:

1. resolves the path inside the selection file's folder, and refuses a path outside it, a symbolic link anywhere on
   the way or inside the policy, and any file that is not UTF-8 text;
2. copies the folder and hashes the copy; everything after this reads the copy, so the code shown is the code built;
3. runs `chock check --only validate` on it;
4. prints every file in full, with the id, the hash and the label (terminal control characters are shown escaped),
   then asks `Type yes to accept`;
5. runs the evals (`chock check --only evals`) only after you accept, because they execute the policy's code;
6. builds it with the catalog members into one plugin.

Any failure stops the install and leaves the previous plugin in place.

**No terminal?** A script, or the chock.sh setup script after it has shown you the code, passes
`--trust-local <id>=<sha256>`. It accepts exactly that hash; a different hash, an unknown id or a piped `yes` refuses.
There is no `--yes`.

**Trust on first use.** The plugin's marker, `chock.selection.json`, records the engine version and commit and every
hash you accepted. Re-installing the same bundle for the same client with unchanged code prints one line per policy
and does not ask; a changed hash shows the code and asks again. The plugin version, `<bundle.version>+<digest12>`,
changes with any local hash.

## 4. Labels

Each custom member reads `custom, not reviewed; <what its hooks do>` in install's output, in `chock bundle status`
and in the plugin's "customize guardrails" skill. Switch one off like any member: `chock bundle off <id>`.

To propose a policy to the catalog instead, follow the catalog's CONTRIBUTING steps and drop the `my-` prefix.
