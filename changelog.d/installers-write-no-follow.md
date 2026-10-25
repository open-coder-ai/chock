- **Hardening: the remaining hook installers write through no link.** The generic, owned-file and session-start
  installers now refuse a symlink or non-regular file anywhere on a hook config's path, as the Claude and Cursor
  installer already did, and replace the file atomically (mode 0600) instead of writing through the path.
