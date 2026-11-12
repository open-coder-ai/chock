- `chock add <id>` with no `--ref` from the default catalog now fetches the catalog release tag
  `v<chock version>`, prints the tag and the commit it resolved to, and records both in
  `chock.lock`. If that tag does not exist it fails and names `--ref <40-hex commit>` or
  `--ref main`; it never falls back to the moving branch. `--ref`, and `--from` another catalog,
  are unchanged.
