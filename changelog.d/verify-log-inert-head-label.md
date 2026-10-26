- **`chock status --verify-log` prints every log-derived value inert** (break fields, chain start, folder labels, the
  confirmed label), and `--head` accepts `<seq>:<sha256>@<log>` to confirm a kept head only in the log it came from.
  The printed head now carries its log and says a head needs keeping outside anything the log's writer can write.
