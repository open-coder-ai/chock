- **`chock install` builds your own policies beside catalog ones (`from: local`).** Install contains each path in
  the selection file's folder (no `..`, no symbolic links, text files only), hashes a snapshot, checks a pinned
  `sha256`, runs `chock check --only validate`, prints every file with its id, hash and the label "custom, not
  reviewed", and asks. The evals run only after you accept, because they execute the policy's code. Without a
  terminal, `--trust-local <id>=<sha256>` accepts exactly that hash; there is no `--yes`. The install marker is
  versioned (engine version and commit, accepted local hashes): an unchanged hash prints one line, a changed one
  asks again. Custom members are labelled "custom, not reviewed" in install's output, `chock bundle status` and the
  "customize guardrails" skill.
- **`chock new policy <id> --kind {content_regex,guard,script,rule,skill}`** writes a template that validates and
  passes its own evals; outside a catalog the id gains `my-`.
- **SEC-5's own remedy now validates.** `ambient_override: true` with an `ambient_override_reason` is in the
  manifest schema, so a sandbox-tier rule passes without claiming review.
