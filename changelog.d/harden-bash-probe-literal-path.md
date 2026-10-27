- **Hardening: the bash probe takes the guard path as an argument.** `find_bash` no longer builds the guard's path
  into the shell string it runs, so a path holding shell syntax is probed as plain text.
