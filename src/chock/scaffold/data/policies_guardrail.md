# Installed policies -- provenance and editing

Policy folders here were installed from a catalog and are hash-pinned in `chock.lock`
(source, version, sha256). They are yours to edit -- but an edited copy no longer matches
its pinned hash, and `chock check --only verify` will report the divergence. To take the
upstream version instead of keeping a local variant, fix it in the source catalog and
reinstall: `chock add <id> --force`, then `chock sync --repo .`.

After any edit here, run `chock sync --repo .` so the compiled gates match the source.
