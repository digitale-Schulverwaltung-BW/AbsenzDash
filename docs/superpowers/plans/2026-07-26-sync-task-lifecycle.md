# Task 1: Keep a strong reference to the background sync task; cancel it on shutdown

## Where this fits

Plan 2 (Backend WebUntis-Sync-Job) and its 2026-07-26 retry-robustness follow-up
changed `_run_main_sync_job` in `backend/app/core/scheduler.py` to fire the sync
run as a fire-and-forget `asyncio.create_task(...)`, so that a slow/retrying sync
(up to ~2h) doesn't block the next regular cron occurrence. The final review of
that follow-up (commit `1ce9bd4` on `main`) flagged one remaining gap, deferred
as a small follow-up:

1. Per Python's asyncio docs, `asyncio.create_task()` results must be held by a
   strong reference somewhere for the lifetime of the task, because the event
   loop only holds a *weak* reference to it — otherwise the task risks being
   garbage-collected mid-execution. `_run_main_sync_job` returns the task (tests
   hold a reference), but no *production* code path holds one, since the
   scheduler just calls `_run_main_sync_job` as a scheduled job and discards its
   return value.
2. `backend/app/main.py`'s FastAPI `lifespan` shutdown calls
   `scheduler.shutdown(wait=False)` but never cancels or awaits any in-flight
   sync task, so an app shutdown mid-sync abandons it silently (asyncio would
   log "Task was destroyed but it is pending").

## Your task

Read this brief — it is your full requirements, with exact values to use
verbatim. This is a single, self-contained task (not part of a larger
multi-task plan): implement the fix, write tests, run tests, commit.

### Files to modify

- `backend/app/core/scheduler.py`
- `backend/app/main.py`
- `backend/tests/test_scheduler.py` (add tests)
- `backend/tests/test_main.py` (add a shutdown-cancellation test) — or a new
  test module if you judge that cleaner; your call, but keep it colocated with
  the existing lifespan/scheduler tests so it's discoverable.

### Required changes

**1. `backend/app/core/scheduler.py`:**

- Add a module-level set to hold strong references to in-flight background
  sync tasks:

  ```python
  _background_sync_tasks: set[asyncio.Task[None]] = set()
  ```

  Place it near the top of the module, after the existing `MAIN_SYNC_JOB_ID`
  constant.

- In `_run_main_sync_job`, right after `task = asyncio.create_task(_run_sync_task())`,
  add the task to that set and register a completion callback that removes it
  again:

  ```python
  _background_sync_tasks.add(task)
  task.add_done_callback(_background_sync_tasks.discard)
  ```

  The function must still `return task` as before (existing tests rely on the
  return value to await it directly).

**2. `backend/app/main.py`:**

- In the `lifespan` shutdown path (after `yield`, currently just
  `scheduler.shutdown(wait=False)`), cancel any tasks still in
  `scheduler_module._background_sync_tasks` and await their cancellation
  before/alongside `scheduler.shutdown()`. Concretely:

  ```python
  from app.core.scheduler import create_scheduler, start_scheduler
  from app.core import scheduler as scheduler_module
  ```

  (or import `_background_sync_tasks` directly — your call, but note it's
  reassignment-sensitive: don't do `from app.core.scheduler import
  _background_sync_tasks` and then rebind that name later, since the module
  code does `_background_sync_tasks.discard(...)` in place on the *module's*
  set object, not a copy. Importing the module and referencing
  `scheduler_module._background_sync_tasks` each time is the safe pattern, or
  import the set object once and only mutate/read it via `.discard()`/
  iteration, never reassign the local name.)

  ```python
  scheduler.shutdown(wait=False)
  pending = list(scheduler_module._background_sync_tasks)
  for t in pending:
      t.cancel()
  if pending:
      await asyncio.gather(*pending, return_exceptions=True)
  ```

  Order relative to `scheduler.shutdown(wait=False)` doesn't matter much here
  (shutdown() doesn't touch the background tasks at all, only APScheduler's own
  job store/executor) — either order is fine, but cancel+gather must happen
  before the `lifespan` context manager returns, since that's what the ASGI
  shutdown sequence waits on.

  You'll need `import asyncio` at the top of `main.py` if it's not already
  there.

### Tests to write

**A. Task survives GC pressure without an external reference (in
`test_scheduler.py`).** Follow the same `asyncio.Event` pattern already used
in `test_run_main_sync_job_reschedules_without_waiting_for_sync_to_finish`
(same file, you can read it for the pattern) — a slow `run_full_sync` replacement
that sets one event and waits on another. The key difference for *this* test:
after calling `_run_main_sync_job`, deliberately do **not** keep your own
reference to the returned task in a place a GC could reach easily — instead,
assert that the task is present in `scheduler_module._background_sync_tasks`
while it's still running (this proves the module itself holds the strong
reference, independent of whatever the test happens to hold). Then trigger a
GC pass (`gc.collect()`) while the sync is still blocked, and confirm the task
is still not done / still in the set — demonstrating it wasn't collected.
Release the sync, await completion, then assert the task has been removed from
`_background_sync_tasks` (the done-callback fired).

**B. Shutdown cancels a pending sync task cleanly (in `test_main.py` or a new
module, your call).** Use the same slow-sync `asyncio.Event` pattern. Drive the
FastAPI `lifespan` context manager directly (it's `app.main.lifespan`, an
`@asynccontextmanager` function taking the `app`) rather than spinning up a
real server — enter it, wait until the sync has started (event set), then exit
the context manager (triggering shutdown) and assert:
- the shutdown completes (the `async with lifespan(app): ...` block exits)
  without raising, within a reasonable timeout (e.g. `asyncio.wait_for(...,
  timeout=2)` around the exit if needed to avoid a hanging test)
- the background task is done and was cancelled (e.g. `task.cancelled()` is
  `True`, or catches `asyncio.CancelledError` appropriately depending on how
  you structure the fake sync coroutine)
- `_background_sync_tasks` is empty afterward

You'll need to monkeypatch `run_full_sync` in `scheduler_module` the same way
the existing scheduler tests do, and you'll need a real `Einstellung` row in
`db_session` (see existing tests) so `start_scheduler`'s cron lookup and the
job's own cron reschedule succeed. Use `pytest.mark.asyncio` on both new
tests, consistent with the rest of the file.

## Global constraints

- Commit messages in English (repo convention).
- Log messages and docstrings in this codebase are German — keep that style
  for any new/changed log lines or docstrings you add (existing code has none
  in these functions currently; don't add new ones unless you need to explain
  a non-obvious constraint).
- No local Python 3.11 interpreter/venv in this worktree. Run all tests via
  the persistent Docker container `absenzdash-test-runner`, already networked
  to the running `absenzdash-db` Postgres container and with
  `requirements-dev.txt` installed:

  ```bash
  docker exec absenzdash-test-runner python -m pytest -q <args>
  ```

  Its workdir `/app` is bind-mounted to this worktree's `backend/` directory,
  so file edits are picked up immediately — no rebuild needed.
- Don't add a mutex/lock around overlapping sync runs — overlapping runs are
  intentional per TECH-SPEC.md §1.3b, not a bug. This task is only about task
  lifetime/GC-safety and clean shutdown, not about serializing runs.
- Don't change `_run_main_sync_job`'s return type or the fact that it returns
  the task — existing tests call `await scheduler_module._run_main_sync_job(...)`
  and then `await task` directly.

## Report

When done, report status (DONE / DONE_WITH_CONCERNS / NEEDS_CONTEXT / BLOCKED),
the commit(s) you made, a one-line test summary (command + pass count), and
any concerns. Run the full test suite once at the end
(`docker exec absenzdash-test-runner python -m pytest -q`) to confirm no
regressions, in addition to the targeted new tests.
