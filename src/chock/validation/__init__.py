"""Facade: single import surface for the validation package."""

import yaml  # noqa: F401  (re-exported for callers/tests)

from chock.validation.checks_content import (  # noqa: F401
    check_description_parity,
    check_no_agent_specific_leakage,
    check_progressive_disclosure,
    check_token_budgets,
    check_yagni,
    extract_skill_md_description,
)
from chock.validation.checks_determinism import (  # noqa: F401
    _compute_script_hashes,
    _hash_file,
    check_determinization_heuristic,
    check_script_integrity,
    check_scripts_shipped,
    check_verb_first_naming,
)
from chock.validation.checks_drift import (  # noqa: F401
    check_registry_freshness,
)
from chock.validation.checks_evals import (  # noqa: F401
    _schema_validate_suite,
    check_eval_first,
)
from chock.validation.checks_manifest_advice import (  # noqa: F401
    check_manifest_advice,
)
from chock.validation.checks_manifest_schema import (  # noqa: F401
    check_manifest_schema,
)
from chock.validation.checks_orchestration import (  # noqa: F401
    check_composition_contract,
    check_dependencies_resolvable,
    check_lifecycle_guards,
    check_subagent_contract,
    check_trust_tier,
)
from chock.validation.checks_repo import (  # noqa: F401
    _ADAPTER_FILES,
    _adapter_file_exists,
    check_adapter_integrity,
    check_ambient_rule_blocks,
    check_ambient_token_budget,
    check_release_consistency,
)
from chock.validation.checks_security import (  # noqa: F401
    _is_adversarial_eval_file,
    _is_script_file,
    _scan_text_surfaces,
    check_ambient_tier,
    check_effects_and_approval,
    check_security_baseline,
)
from chock.validation.engine import (  # noqa: F401
    main,
    validate_artifact,
)
from chock.validation.frontier import (  # noqa: F401
    check_frontier_mode,
    load_frontier_standard,
)
from chock.validation.loading import (  # noqa: F401
    BUDGETS,
    SCHEMA_DIR,
    count_lines,
    discover_artifacts,
    find_manifest,
    get_validator,
    load_schema,
    schema_validator,
    validate_yaml_against_schema,
)
from chock.validation.patterns import (  # noqa: F401
    _DETERMINISTIC_HEURISTIC_PATTERNS,
    _INT3_GRANDFATHERED_IDS,
    _VERB_PREFIXES,
    AGENT_SPECIFIC_KEYWORDS,
    AGENT_SPECIFIC_PATTERNS,
    DEPTH_MARKERS,
    INJECTION_PATTERNS,
)
from chock.validation.report import (  # noqa: F401
    Finding,
    Report,
    emit,
)
