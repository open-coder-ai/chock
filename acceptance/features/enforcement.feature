Feature: Enforcing a policy
  Does a policy that declares a gate actually stop something?

  Tested with a fixture policy the suite owns, never a shipped one. Using scan-secrets
  here would mean tightening its regex could fail this suite, and would only show the
  framework works for policies we ship -- when the claim is that it works for any policy
  an adopter writes. Shipped-policy correctness is tier 2.

  Background:
    Given a fresh repository
    And the repository is onboarded

  Scenario: A declared gate blocks matching content
    Given a policy blocking "acceptance-forbidden-token" is installed
    And hooks are installed
    And the adopter is on a feature branch
    When they commit "config.py" containing "acceptance-forbidden-token"
    Then the commit is blocked
    And the output mentions "acceptance guard"

  Scenario: The same gate allows unrelated content
    # Over-blocking is the failure that gets a guard switched off.
    Given a policy blocking "acceptance-forbidden-token" is installed
    And hooks are installed
    And the adopter is on a feature branch
    When they commit "app.py" containing "print('ordinary code')"
    Then the commit succeeds

  Scenario: A gate is inert until hooks are installed
    # Compiling is not enforcing. That distinction is the whole coverage model.
    Given a policy blocking "acceptance-forbidden-token" is installed
    And the adopter is on a feature branch
    When they commit "config.py" containing "acceptance-forbidden-token"
    Then the commit succeeds

  # The PreToolUse guards are the one surface that cannot be exercised with a synthetic
  # policy: the emitter matches guard scripts by policy id, so only a real guard policy
  # produces a fragment. init no longer installs one, so these copy it in first -- which is
  # also the adoption path an adopter now takes.

  Scenario Outline: Destructive commands are refused before they run
    # Driven with the payload Claude Code actually sends to a PreToolUse hook.
    Given the guard policies are copied in
    And hooks are installed
    When the agent attempts "<command>"
    Then the attempt is refused

    Examples:
      | command                     |
      | rm -rf /                    |
      | git commit --no-verify -m x |

  Scenario Outline: Safe commands are not refused
    Given the guard policies are copied in
    And hooks are installed
    When the agent attempts "<command>"
    Then the attempt is allowed

    Examples:
      | command                                  |
      | ls -la                                   |
      | git push --force-with-lease origin main  |

  Scenario: Installed hooks use the documented schema
    # A fragment Claude Code cannot parse enforces nothing, however well it installs.
    Given the guard policies are copied in
    And hooks are installed
    Then the file ".claude/settings.json" exists
    And the file ".chock/bin/pretooluse.py" exists
    And every installed hook uses the documented schema

  Scenario: Installation preserves a hand-written hook
    # The settings file belongs to the adopter.
    Given the adopter has a hand-written PreToolUse hook
    And hooks are installed
    Then the hand-written hook survives
    And their other settings survive

  Scenario: Coverage never claims more than is installed
    # With nothing installed the check is vacuous, so give it a policy to be wrong about.
    Given a policy blocking "acceptance-forbidden-token" is installed
    When the adopter runs "recompile --repo . --skip-hooks"
    Then no policy claims enforcement without a compiled gate
