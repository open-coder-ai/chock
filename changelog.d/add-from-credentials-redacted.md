- **Hardening: `chock add --from` never stores or prints a URL's credentials.** The `user:token@` part of a
  catalog URL is dropped before the source is written to `chock.lock`, printed, or put in an error message.
