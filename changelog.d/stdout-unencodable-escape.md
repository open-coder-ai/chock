- **Command output no longer crashes on a character the stream cannot encode.** `chock check` on a
  Windows runner (stdout cp1252) raised `UnicodeEncodeError` on U+FFFD while printing eval results. The
  stdout wrapper now retries with `backslashreplace` in the stream's encoding; text the encoding can
  represent prints unchanged.
