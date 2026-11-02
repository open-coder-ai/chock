- The vendored runtime renders byte-identically on every supported Python. Five f-strings whose replacement fields held
  quoted strings were printed with different quotes by `ast.unparse` on Python 3.12.3 than on 3.12.13, so `chock sync`
  on one patch level failed `sync --check` on another. They are rewritten, so the next `chock sync` rewrites `.chock/bin`
  once.
