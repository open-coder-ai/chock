- **Hardening: `chock plugin build` in place refuses a symlink under the policy tree.** The build no longer
  writes through a link at any path it generates; it stops with an error naming the link and writes nothing.
