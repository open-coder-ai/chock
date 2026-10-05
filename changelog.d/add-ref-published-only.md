- **Security: `chock add --ref <sha>` accepts only a commit on a branch or tag the source publishes.** A
  remote can serve by id any commit in its repository network, including a fork's or a
  `refs/pull/N/head` commit, so a copied `--from <official url> --ref <sha>` could install code the
  source never published. After the commit is fetched, `add` now fetches the source's branches and tags
  (no blobs) and refuses, installing nothing (exit 2), unless the commit is reachable from one of them;
  `refs/pull/*` and other namespaces never count and there is no override. To use a fork's commit, pass
  the fork's own URL as `--from`. A local directory source is the user's own checkout and is not
  checked; branch and tag refs are unchanged.
