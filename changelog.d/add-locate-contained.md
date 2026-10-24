- **Hardening: `chock add` finds a pack only inside the catalog.** The fallback lookup (`<area>/<id>`) now
  applies the same containment check as a `registry.yaml` entry, a pack directory that is itself a symlink
  is refused, and the copy never follows a link.
