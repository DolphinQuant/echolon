"""
Feature Flags for Skills and Hooks Migration

This module provides feature flags to enable/disable Skills and Hooks
functionality for rollback support during the migration.

Usage:
    from echolon.config.feature_flags import FEATURES

    if FEATURES['USE_SKILLS']:
        options.setting_sources = ["project"]

    if FEATURES['USE_HOOKS']:
        options.hooks = hook_config
"""

# Feature flags for migration rollback support
FEATURES = {
    # Phase 1: Skills (load from .claude/skills/)
    'USE_SKILLS': True,

    # Phase 2: Hooks (PreToolUse and PostToolUse validation)
    'USE_HOOKS': True,

    # Phase 4: Agent consolidation (reduce 17 agents to 9)
    # Start False until Phase 4 is implemented
    'USE_CONSOLIDATED_AGENTS': False,
}


def is_feature_enabled(feature_name: str) -> bool:
    """
    Check if a feature is enabled.

    Args:
        feature_name: Name of the feature to check

    Returns:
        True if enabled, False otherwise

    Raises:
        KeyError: If feature_name is not a valid feature
    """
    return FEATURES[feature_name]


def enable_feature(feature_name: str) -> None:
    """Enable a feature flag."""
    FEATURES[feature_name] = True


def disable_feature(feature_name: str) -> None:
    """Disable a feature flag."""
    FEATURES[feature_name] = False
