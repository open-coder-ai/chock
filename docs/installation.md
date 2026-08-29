# Installation

Chock ships as a PyPI package, a GitHub Action, and a source install. Every method can run
`chock init` in a clean environment with a freshly initialized git repo.

> **Early access.** The standalone binary, the Homebrew tap and the Scoop bucket below are
> **planned, not published** — those sections are marked, and their commands will not work yet.

> **Runtime caveat:** the installed git hooks are bash shims that call the vendored Python
> runner, so hook runtime always needs a bash shell **and** a Python 3.11+ interpreter on
> `PATH` (`python3`, `python`, or `py` — one that can import `tomllib`), whichever way the CLI
> was installed. Git for Windows includes bash on Windows.

## pipx (recommended)

```bash
pipx install chock
chock --version
chock init .
```

`pipx` keeps the CLI isolated and on `PATH`.

## pip

```bash
pip install chock
chock --version
chock init .
```

Use `python -m chock …` if your scripts directory is not on `PATH`.

## Standalone binary — not published yet

No release assets exist yet, so there is nothing to download today. Documented as the
intended shape; use pipx, pip, or a source install meanwhile.

The plan: download the one-file executable for your OS from the
[latest release](https://github.com/open-coder-ai/chock/releases/latest):

| OS | Asset |
| :--- | :--- |
| Linux | `chock-ubuntu-latest` |
| macOS | `chock-macos-latest` |
| Windows | `chock-windows-latest.exe` |

Place it on `PATH` and run:

```bash
chock --version
chock init .
```

The binary will bundle its own interpreter for CLI commands, but the git hooks it installs
still need bash and a Python 3.11+ interpreter on `PATH` at hook runtime.

## Homebrew — not published yet

The tap `open-coder-ai/chock` does not exist, so this fails today. Documented as the
intended shape; use pipx, pip, or the standalone binary meanwhile.

```bash
brew tap open-coder-ai/chock
brew install chock
chock --version
chock init .
```

## Scoop — not published yet

The bucket `open-coder-ai/scoop-bucket` does not exist, so this fails today. Documented as the
intended shape; use pipx, pip, or the standalone binary meanwhile.

```bash
scoop bucket add chock https://github.com/open-coder-ai/scoop-bucket.git
scoop install chock
chock --version
chock init .
```

## Source

```bash
git clone https://github.com/open-coder-ai/chock.git
cd chock
pip install -e '.[dev]'   # add '.[build]' to build wheels/binaries
chock --version
chock init .
```

## GitHub Action

Use the action in a workflow:

```yaml
- uses: open-coder-ai/chock@v0.6.0
  with:
    command: check
    version: 0.6.0
```

The action installs the pinned version via `pipx` and runs the command. The `v1` major
tag tracks the latest 1.x-compatible release and is created with the first public
release — before that release exists, pin a full commit SHA instead.

## Clean-install test

A valid install must pass the same acceptance test used in CI:

```bash
mkdir -p /tmp/ac-smoke && cd /tmp/ac-smoke
git init --quiet
chock init .
```

If `init` completes with `Initialized Chock in <path>` and
`Policies: none. This repo enforces nothing yet.`, the install is healthy.
