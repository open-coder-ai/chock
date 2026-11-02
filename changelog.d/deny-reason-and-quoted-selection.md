- **A refusal says why, and `--selection` takes a quoted code.** A hook deny now reads `Blocked by chock policy:
  <policy>: <the guard's own line>` (for example `BLOCKED: destructive rm command targeting '.git' is not allowed
  without approval.`), the way an ask already carried its reason; exit codes and each client's JSON are unchanged.
  `chock install --selection` strips one surrounding pair of single or double quotes before decoding, because
  cmd.exe passes them through, and a code that still fails to decode says so.
