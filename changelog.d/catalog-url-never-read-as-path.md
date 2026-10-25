- **Hardening: a catalog URL is never read as a path in the working directory.** A source spelled as a URL
  or `user@host:path` is always fetched from the remote, and its published-branch checks always run, even
  when a directory of the same shape exists under the current directory. A local catalog is a path.
