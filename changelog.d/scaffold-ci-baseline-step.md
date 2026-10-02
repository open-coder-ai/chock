- **The workflow `chock sync --ci` installs refuses a pull request that weakens the policy set.** A
  new step runs `chock check --only baseline --base "origin/$BASE_REF"` on `pull_request`, before the
  compiled gates, with the base branch passed through `env:` (never `${{ }}` in shell text) and read
  from the checkout's full history (`fetch-depth: 0`); a base that does not resolve fails the step.
  chock's own CI already ran it; adopters now get it on their next `chock sync --ci`. A
  `pull_request` run uses the pull request's own copy of the workflow, so a pull request that also
  deletes the step is not caught by it; nothing yet checks the installed workflow against the template.
