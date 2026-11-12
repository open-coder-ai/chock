- Each defaulted manifest field is warned about once per command, always with the artifact's path:
  `chock check` no longer repeats a skill's eleven `manifest_default` warnings, two copies of them with
  no path (IR-F75). The registry scan's copy now goes to stderr with the others.
- On a console stream that is not UTF (a Windows code page such as cp1252), chock prints ASCII for its
  own symbols: the eval table's truncation reads `...`, not U+2026 shown as another letter (IR-F76).
