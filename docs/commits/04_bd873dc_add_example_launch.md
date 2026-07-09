# bd873dc — Add example launch via vultr

**Date:** 2026-07-03
**Author:** alinzh

Added a standalone script for submitting a CRYSTAL calculation through
AiiDA to the yascheduler, to test the Vultr integration end-to-end
without manual SSH steps.

## Files changed (1 file, +35)

### Added

- **`examples/vultr_test_aiida.py`** — submits `MPDSStructureWorkChain`
  (geometry optimization, no phonons/elastic/properties) for a given
  formula and space group (defaults: MgO 225). Uses the `nonmetallic.yml`
  template from `mpds_aiida`. Prints the submitted workchain PK.

  Usage:
  ```
  export MPDS_KEY=...
  python examples/vultr_test_aiida.py [formula] [sgs]
  ```

## Note

The module docstring was later expanded in commit `eec67b9` to mention
the Seebeck pipeline script (`run_seebeck_easy_example_HCL_225.py`) as an
alternative for full Seebeck calculations.