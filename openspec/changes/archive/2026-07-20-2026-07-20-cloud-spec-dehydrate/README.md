# cloud-spec-dehydrate

Trim the `cloud` spec to requirements + scenarios; relocate method-level pre/post-conditions, invariants, and architectural rationale into GRACE markup on `yascheduler/infra/cloud/*` and `yascheduler/entrypoints/config_parser.py`. No behavioral change; every observable scenario preserved.
