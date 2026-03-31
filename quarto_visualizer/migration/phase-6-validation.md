# Phase 6 Validation Report

- Config: `C:\Users\wesley.darling\projects\activitysim_visualizer\config.yaml`
- Reference bundle: `C:\Users\wesley.darling\projects\activitysim_visualizer\artifacts\panel_reference`
- Runs: 2
- Modes: weighted, unweighted

## Summary

- `bundle-projection`: 101/101 checks passed
- `dashboard-structure`: 3/3 checks passed
- `manifest`: 5/5 checks passed
- `reference-replay`: 104/104 checks passed
- `selectors`: 10/10 checks passed

## Result

- All recorded parity checks passed.

## Remaining Manual Follow-Up

- Static export behavior remains a manual UI check; the validator does not assert disabled controls in rendered HTML.
- Geography-enabled, mode-group-enabled, and 24-bin timing scenarios still need config/data coverage beyond the current default reference bundle.
- Percent vs Count visual behavior is preserved in code, but still benefits from an explicit interactive smoke test because many density charts intentionally stay normalized.
