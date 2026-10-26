- **A guard's exit-1 refusal stays a deny when it echoes command text:** a crash is now recognised only from the
  interpreter's own opening line (a traceback, a `File "...", line N` syntax error, bash's `<script>: line N: syntax
  error`) or from no output, never from words elsewhere in the output. Changes the vendored runtime: a person runs
  `chock sync` to render it.
