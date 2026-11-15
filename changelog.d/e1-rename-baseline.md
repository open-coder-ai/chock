- A gate judges a file that git reports as renamed (`-M`) against its old path's content, for a script gate and a
  `content_regex` gate, at commit, at the turn's end and on the CI range. A pure `git mv` of a file holding an old
  finding is no longer refused as new work; a new finding added in the move is, and a copy (old path kept) is judged
  as new, as before.
