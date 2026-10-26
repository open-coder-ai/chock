- **Hardening: a hook command refuses a word a shell would read.** `hook_command` accepts plain words and
  double-quoted paths without `"`, `$`, a backtick, a backslash or a line break; any other word raises
  instead of being joined into the command line.
