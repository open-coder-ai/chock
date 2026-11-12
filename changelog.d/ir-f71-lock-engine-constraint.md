- `chock.lock`'s `engine` field is now true and read (IR-F71): `sync` writes `>=<major>.<minor>,<<major+1>`
  derived from the running engine (`>=1.1,<2` at 1.1.x, was the stale `>=0.1,<0.2`), and `chock check --only verify`
  fails with one line naming the running engine, the lock's constraint and the fix (`pip install` a matching chock,
  or `chock sync --repo .` with the newer engine) when the engine is outside it. A lock that still says `>=0.1,<0.2`
  passes with a one-line note to run `chock sync`; a missing or unparseable constraint fails.
