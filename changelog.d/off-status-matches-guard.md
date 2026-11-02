- **A repo-scope `off` the guard does not honour is no longer reported as off.** The session-start notice now lists an
  `off` that HEAD's copy of the toggle file does not hold as staying on until that change is committed, as
  `chock bundle status` already did, and `chock bundle off` at repo scope ends with a line saying the change applies
  only once the file is committed and from the next session. User scope is unchanged.
