- **Hardening: `chock eval export` writes only under `--out`.** A policy whose manifest `id` is not a valid
  policy id (`^[a-z][a-z0-9-]{2,63}$`) is reported as an error and exports nothing.
