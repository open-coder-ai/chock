- `chock check --floor`: a path listed only because an any-depth pattern matched it below the top level
  (`node_modules/x/.claude/...`) is followed by the pattern that matched it (`matched **/.claude/**`). A base
  `remove:` entry that is the old top-level form of a default (`.claude/**`) names the pattern to write
  (`**/.claude/**`). A base `.chock/config.yaml` that is a folder, a symbolic link, a submodule or not UTF-8 is
  undecided (exit 2). When base and head are the same commit the run says that nothing changed. The `--floor`
  help says a link may also open nothing. Release gate G1 (GT-2): regression tests for patterns, config, SARIF,
  abnormal paths and ordinary pull requests, and a map from every behaviour sentence in `docs/floor.md` and the
  `--floor` help to the test that proves it.
