## Problem

When clicking "Complete Initialization", if QMT is detected as not running, the current flow is:
- A generic progress dialog appears ("正在自动启动 QMT 客户端并测试连接，请稍候...")
- Auto-start + connection test executes synchronously on the server
- If it fails, a failure page is shown (with retry button)

Issues:
1. The progress dialog text is generic and doesn't differentiate between "QMT not running, attempting to start" vs "QMT already running, reconnecting" scenarios
2. Auto-starting QMT is synchronous and blocking (can take 20s+), the user sees only a static loading spinner
3. After auto-start fails, the user has to navigate away from the current page to retry

## Desired Behavior

1. When clicking "Complete Initialization" and QMT is detected as NOT running → show a dedicated dialog:
   - "检测到 QMT 未运行" (QMT is not running)
   - "正在尝试自动启动 QMT 客户端，请稍候..." (Attempting to auto-start QMT, please wait...)
   - Auto-trigger the startup flow
2. If auto-start fails → dialog updates to error state with a "重试" (Retry) button
3. If auto-start succeeds → auto-redirect to homepage

## Technical Approach

1. Modify `wizard_complete`: when QMT path is valid but QMT is not running, return a "waiting dialog" fragment instead of synchronously running `_try_recover_qmt_for_wizard`
2. The dialog auto-triggers `/init-wizard/retry-startup` via HTMX
3. `/init-wizard/retry-startup` handles the actual startup + connection test + completion
4. On failure, dialog updates to error state with retry button

## Files Involved

- `qmt_gateway/app.py` - modify `wizard_complete` and `wizard_retry_startup`
- `qmt_gateway/web/pages/init_wizard.py` - add new dialog component
- `tests/test_init_wizard.py` - update test cases
