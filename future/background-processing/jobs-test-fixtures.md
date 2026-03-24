---
related:
  - jobs-structured-logging
---

# Job testing fixtures

Currently there's no test support for jobs. When `run_in_worker()` is called in a test, it creates a `JobRequest` DB row but no worker is running to process it. Need fixtures so app tests can verify job side effects.

## Recommended: `run_jobs` fixture (enqueue normally, process on demand)

```python
def test_signup_sends_welcome(db, run_jobs):
    client.post("/signup/", data={...})
    # Job is enqueued as a real JobRequest row
    assert JobRequest.query.count() == 1

    run_jobs()  # process pending jobs synchronously, in-process

    assert JobRequest.query.count() == 0
    assert Email.query.count() == 1
```

Implementation: a callable that queries pending `JobRequest` rows, loads the job class, deserializes params, calls `run()`, and converts to `JobResult` — all within the test's DB transaction. Exercises the real enqueue path (priority, delay, concurrency_key, `should_enqueue()`) but runs in-process.

Could accept filters for more control:

```python
run_jobs()                          # all pending
run_jobs(job_class=WelcomeEmailJob) # just this type
run_jobs(queue="emails")            # just this queue
```

## Maybe later: `eager_jobs` fixture (skip the queue entirely)

```python
def test_signup_sends_welcome(db, eager_jobs):
    client.post("/signup/", data={...})
    # WelcomeEmailJob.run() already executed synchronously
    assert Email.query.count() == 1
```

Monkepatches `run_in_worker()` to call `self.run()` directly. Simplest but skips entire enqueue path — no JobRequest rows, no priority/delay/concurrency_key, no `should_enqueue()`.

## Not recommended (for now): worker thread fixture

Spinning up a real worker in a background thread is the most realistic but hardest to get right — transaction visibility issues with the `db` fixture, timing/polling complexity, fragile. Not worth it unless specifically testing worker behavior.
