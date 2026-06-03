## 1. Migration

- [ ] 1.1 Replace `@attr.s(auto_attribs=True, frozen=True)` with `@dataclass(frozen=True)` in config.py
- [ ] 1.2 Migrate config/db.py
- [ ] 1.3 Migrate config/local.py
- [ ] 1.4 Migrate config/remote.py
- [ ] 1.5 Migrate config/cloud.py
- [ ] 1.6 Migrate config/engine.py
- [ ] 1.7 Migrate config/engine_repository.py
- [ ] 1.8 Simplify config/utils.py — remove make_default_field
- [ ] 1.9 Replace `evolve()` with `replace()` in all config code
- [ ] 1.10 Update GRACE-lite markup in all config files

## 2. Tests

- [ ] 2.1 Run existing `test_config.py` (35 tests) — all pass with dataclasses
- [ ] 2.2 Add roundtrip test: serialize/deserialize config has identical values

## 3. Verification

- [ ] 3.1 Run `openspec validate --all --json`
- [ ] 3.2 Run full test suite — no regressions
- [ ] 3.3 Verify `attrs` imports removed from config/
