- **Internal: the gate runner is a package, `chock.gate.runner`, no longer one 1,482-line file.**
  Ten modules (constants, context, actor, kinds, script, log, material, report, verdict, cli), each
  under 300 lines and with no import cycle. Every public name, and the private helpers chock's own
  code reads, is re-exported, so `from chock.gate.runner import ...` keeps working (the other private
  helpers and stdlib imports now live only in their module); `python -m chock.gate.runner` still runs
  the command line. The vendored `.chock/bin/gate.py` stays
  one stdlib-only file: `chock.gate.assemble` builds it from a prelude and the modules' numbered
  fragments, refuses to build if a declared module or fragment is missing, and its output is
  byte-identical to the old `runner.py`. No change to what any gate decides.
