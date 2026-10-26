- **Hardening: the rendered runtime no longer depends on the Python patch release.** Python 3.12.0 to 3.12.x
  `ast.unparse` writes same-quote nested f-strings that are a SyntaxError on 3.11; the renderer now lowers any
  f-string holding a string literal to plain `''.join([...])` source, so the runtime is byte-identical and
  parses on 3.11 whichever supported interpreter renders it.
