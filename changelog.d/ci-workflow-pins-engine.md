- **`chock sync --ci` pins the engine in the generated workflow.** It used to install
  `git+https://github.com/open-coder-ai/chock` with no ref, so an adopter's CI ran whatever chock
  `main` held. It now installs the exact commit that generated the file (the same commit the install
  marker records). When no commit is known (a PyPI install), it pins the installed version from PyPI
  and says so in a comment. Re-run `chock sync --ci` to move the pin.
