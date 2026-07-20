# engine-config-parsing-spec-trim

Trim `engine-config-parsing` spec to requirements + scenarios only; relocate the validator-location invariant, the layering rationale, and the duplicated `engine_valid_fields` narrative into GRACE markup on `yascheduler/entrypoints/config_parser.py` (engine-related regions) and `yascheduler/domain/engine.py` (`CLASS_Engine`).
