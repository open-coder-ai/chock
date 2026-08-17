Feature: Onboarding a repository
  An adopter installs Chock and starts working.

  Every scenario here would have failed at some point on 2026-08-04 while the internal
  suite was green: the wheel was missing 42 template files, init installed 10 of the 12
  policies it then bundled, and a clean install warned about every policy it had installed.

  Bundling is gone. The framework ships mechanism, not content, so init now installs no
  policies at all -- and the scenarios that used to assert it installed every one of them
  assert the opposite, plus the notice that makes the absence visible to an adopter.

  Background:
    Given a fresh repository

  Scenario: Init scaffolds the repository
    When the adopter runs "init ."
    Then the command succeeds
    And the file "AGENTS.md" exists
    And the file ".chock/config.yaml" exists
    And the file ".agents/policies/INDEX.md" exists

  Scenario: A clean install validates without warnings
    Given the repository is onboarded
    When the adopter runs "validate ."
    Then the command succeeds
    And the output does not mention "WARN"

  Scenario: Init installs no policies
    # The inverse of what this scenario used to assert. Nothing framework-owned is written
    # into .agents/policies, which is what makes an adopter's copy safe from the next init.
    When the adopter runs "init ."
    Then the command succeeds
    And no policies are installed

  Scenario: Init says the repo is unguarded and how to fix it
    # An unprotected repo is a real regression in first experience. It is acceptable only
    # if the adopter is told, so the notice is a scenario, not a nicety.
    When the adopter runs "init ."
    Then the command succeeds
    And the output mentions "enforces nothing yet"
    And the output mentions "chock sync --repo ."

  Scenario: Listing policies in a scaffolded repo says so in words
    Given the repository is onboarded
    When the adopter runs "policies"
    Then the command succeeds
    And the output mentions "No policies installed"

  Scenario: Init is idempotent
    Given the repository is onboarded
    And the current index is recorded
    When the adopter runs "init ."
    Then the command succeeds
    And the index is unchanged

  Scenario: The index is fresh after init
    Given the repository is onboarded
    When the adopter runs "refresh --check"
    Then the command succeeds

  Scenario: The lockfile matches after init
    Given the repository is onboarded
    When the adopter runs "verify"
    Then the command succeeds

  Scenario: Ordinary work still commits
    # A guard that bricks the repo is worse than no guard.
    Given the repository is onboarded
    And the adopter is on a feature branch
    When they commit "app.py" containing "print('hello')"
    Then the commit succeeds
