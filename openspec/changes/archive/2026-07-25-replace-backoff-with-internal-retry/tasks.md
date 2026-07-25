## 1. Create internal retry utility

- [x] 1.1 Create `yascheduler/shared/retry.py` with `retry()` function supporting decorator, partial, and direct-call forms per design
- [x] 1.2 Write unit tests for `shared/retry.py` covering: matching exception retries, non-matching exception propagates, giveup stops retry, max_time deadline, successful call returns result, partial form, direct-call form

## 2. Replace backoff in production code

- [x] 2.1 Replace `@backoff.on_exception(backoff.fibo, ...)` in `webhook.py` with `@retry(on=aiohttp.ClientError, max_time=60)`
- [x] 2.2 Replace `@backoff.on_exception(backoff.fibo, ...)` in `vastai.py` with `@retry(on=VastAIError, max_time=60, giveup=...)`, preserving `giveup` lambda
- [x] 2.3 Rename `my_backoff_exc` to `my_retry` in `session.py` — change partial to `partial(retry, on=SSHRetryExc, max_time=60)` and update all 3 usages within the file
- [x] 2.4 Rename `my_backoff_sftp` to `my_retry` in `download.py` — change partial to `partial(retry, on=SFTPRetryExc, max_time=60)` and update the single usage within the file
- [x] 2.5 Update `repository.py` — import `my_retry` from `session.py` instead of `my_backoff_exc`

## 3. Clean up backoff dependency and test references

- [x] 3.1 Remove `backoff~=2.1.2` from `pyproject.toml` dependencies and the `DeprecationWarning` suppression filter
- [x] 3.2 Update `test_webhook_handler.py` — replace `_fast_backoff` fixture to work with new retry utility instead of `backoff._async` internals
- [x] 3.3 Update `test_ssh_gateway_download_outputs.py` — `_no_sftp_backoff` fixture now patches `my_retry` from new retry
- [x] 3.4 Remove `test_backoff_level_error` from `test_daemon_common.py`
- [x] 3.5 Remove `"backoff"` from `FORBIDDEN_NAMES` in `test_application_no_adapter_imports.py`
- [x] 3.6 Verify `backoff` is fully removed: no imports, no fixtures, no deprecation warning filter remain in production or test code
