- **`chock witness export` re-keys every record's `target` fingerprint** with a random key made for that export and
  discarded, so equal targets still match inside the file but a guessed path or command cannot be confirmed offline.
