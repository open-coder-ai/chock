- **Hardening: the pack hash is length-prefixed, and `chock.lock` is now `lockfile_version` "2".** The old
  `name NUL content NUL` stream let two different file sets hash alike when a file held a NUL byte. Each
  name and content now carries its length. **Migration:** run `chock sync` once and commit `chock.lock`.
  Until then a version 1 hash (in `chock.lock`, a selection's `sha256`, or `--verify-sha`) still matches a
  pack that holds no NUL byte, where the old framing is unambiguous; for a pack that does, it no longer
  matches and `chock check` asks for the sync. `chock plugin` marketplace locks keep the old hash for now.
