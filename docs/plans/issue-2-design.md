# Verbose Fastchess Output Streaming Design

**Issue:** #2
**Goal:** Allow users to see real-time fastchess subprocess output by passing a `--verbose` flag to the client CLI.

## Architecture

The change adds an opt-in `--verbose` / `-v` flag to the client CLI that controls whether
the fastchess subprocess output is streamed to the terminal in real time. When the flag is
absent, behavior is identical to today: fastchess output is captured silently and written to
`workspace/fastchess.log` after completion.

The flag is threaded from the CLI entry point through `OpenEloClient` into `MatchRunner` as
a boolean instance variable set once at construction time. `MatchRunner` runs one job at a
time (no concurrency), so an instance variable is sufficient.

**Key design decisions:**

1. **Opt-in boolean flag** — Default behavior remains quiet. No verbosity levels; a simple
   `--verbose` matches the issue's language ("a verbose flag").

2. **Single `Popen`-based subprocess path** — Both verbose and quiet modes use
   `subprocess.Popen(stdout=PIPE, stderr=STDOUT)` with line-by-line reading. In quiet mode,
   lines are accumulated silently. In verbose mode, each line is also printed via
   `Console.status("FC", ...)`. This avoids maintaining two divergent subprocess code paths
   while keeping both modes functionally equivalent in terms of log capture.

3. **Tee pattern** — Every line read from the subprocess is accumulated into a buffer
   regardless of verbose mode. After the process exits, the buffer is written to
   `fastchess.log` and is available for error diagnostics. This preserves the existing log
   file behavior and error messages.

4. **Thread-safe `Console`** — A `threading.Lock` is added to `Console` to prevent
   interleaved output between the main thread's fastchess streaming loop and the heartbeat
   daemon thread, which calls `Console.status("WARN", ...)` on failure.

5. **Bench excluded** — `_run_bench()` remains unchanged (`subprocess.run` with
   `capture_output=True`). Bench runs are short-lived (seconds), their output is parsed for
   NPS values, and the issue specifically targets fastchess visibility.

## Components

### 1. CLI argument — `client/app/main.py`

- **Purpose**: Expose `--verbose` / `-v` flag to the user.
- **Change**: Add to `build_parser()`:
  ```python
  parser.add_argument(
      "--verbose", "-v",
      action="store_true",
      default=False,
      help="Stream fastchess output to the terminal in real time",
  )
  ```
- **Propagation**: Pass `args.verbose` to `OpenEloClient(verbose=args.verbose, ...)` in
  `main()` (line 47).

### 2. `OpenEloClient` — `client/app/runtime/client.py`

- **Purpose**: Accept `verbose` parameter and forward it to `MatchRunner`.
- **Change**: Add `verbose: bool = False` parameter to `__init__` (after existing params).
  Store as `self.verbose`. Pass to `MatchRunner(verbose=self.verbose, ...)` at line 98.
- **No other behavioral changes** — the heartbeat thread, registration, and job loop are
  untouched.

### 3. `MatchRunner` — `client/app/runtime/match_runner.py`

- **Purpose**: Execute the fastchess subprocess with optional real-time output streaming.
- **Change**: Add `verbose: bool = False` parameter to `__init__`, stored as
  `self.verbose` instance variable.
- **`run()` method** (replaces line 130): Replace `subprocess.run(command,
  capture_output=True, ...)` with a `Popen`-based block:
  ```python
  output_lines: list[str] = []
  with subprocess.Popen(
      command,
      cwd=self.workspace.root,
      stdout=subprocess.PIPE,
      stderr=subprocess.STDOUT,  # stderr merged into stdout
      text=True,
  ) as process:
      assert process.stdout is not None  # guaranteed by stdout=PIPE
      for line in process.stdout:
          stripped = line.rstrip("\n\r")
          output_lines.append(stripped)
          if self.verbose:
              self.console.status("FC", stripped)
  rc = process.wait()
  log_text = "\n".join(output_lines).strip()
  ```
  Because `stderr=subprocess.STDOUT` is used, there is no separate stderr stream;
  `process.stderr` is `None` and must not be read. All error output from fastchess is
  captured through the single stdout pipe.
- **`_run_bench()` (line 254)**: Intentionally unchanged. Bench is short-lived and its
  output is parsed for NPS values, not intended for user display.

### 4. `Console` — `client/app/runtime/console.py`

- **Purpose**: Thread-safe terminal output.
- **Change**: Add a `threading.Lock` as a dataclass field:
  ```python
  import dataclasses
  import threading

  @dataclass(slots=True)
  class Console:
      _lock: threading.Lock = dataclasses.field(default_factory=threading.Lock)
  ```
  Wrap the body of `_print()` with `with self._lock:`. This ensures that:
  - Multi-line methods like `section()` (which calls `_print` multiple times) are not
    interrupted by a heartbeat `status("WARN", ...)` call from the daemon thread.
  - Fastchess output lines in verbose mode do not interleave with any other console output.

  The lock is acquired per `_print` call (not per public method) to keep the locking
  granularity simple and avoid deadlock with a non-reentrant lock.
- **No new methods** — fastchess output uses the existing `status(tag, message)` method
  with tag `"FC"`.

## Data Flow

### Primary use case: verbose fastchess run

1. User starts: `python3 app/main.py --server ... --access-key ... --threads 16 --hash 512 --verbose`
2. `main.py` passes `verbose=True` to `OpenEloClient.__init__`, which stores it and passes
   it to `MatchRunner.__init__`.
3. When a job is received, `MatchRunner.run()` builds the fastchess command (unchanged).
4. A `Popen` process is created with `stdout=PIPE, stderr=STDOUT, text=True`.
5. The main thread enters a `for line in process.stdout:` loop:
   - Each line is stripped and appended to `output_lines: list[str]`.
   - `self.console.status("FC", stripped)` prints the line to the terminal.
6. When the loop exhausts (stdout EOF), `process.wait()` is called to collect the return
   code from `process.returncode`.
7. `log_text = "\n".join(output_lines).strip()` — written to `fastchess.log`.
8. Return code check, PGN parsing, and result reporting proceed identically to current code.

### Non-verbose (default) path

Identical to above, except step 5 skips the `console.status` call. Lines are accumulated
silently. The result is functionally equivalent to the current `subprocess.run(capture_output=True)`.

### Concurrent heartbeat

The `_HeartbeatThread` daemon calls `console.status("WARN", ...)` every 15 seconds on
failure. The `Console._lock` acquired inside `_print()` ensures heartbeat warnings do not
split multi-line `section()` output or interleave with fastchess streaming lines.

## Error Handling

### Fastchess subprocess failure (non-zero return code)

After `process.wait()`, check `process.returncode != 0`. Raise
`RuntimeError(log_text or f"fast-chess exited with return code {process.returncode}")` —
identical to current behavior. `log_text` is available because lines were accumulated in
both verbose and quiet modes via the tee pattern.

### Process cleanup on exception

The `Popen` call and line-reading loop use the `with subprocess.Popen(...) as process:`
context manager. If an exception occurs mid-loop (e.g., `KeyboardInterrupt`,
`BrokenPipeError` from `print`):

- `Popen.__exit__` is called, which invokes `process.communicate()` to wait for the child
  to exit naturally. Note: `Popen.__exit__` does **not** send SIGKILL — it waits.
- If the implementation requires immediate termination on interrupt (rather than waiting for
  fastchess to finish), an explicit `try/finally` should call `process.kill()` then
  `process.wait()` inside the `with` block:
  ```python
  with subprocess.Popen(...) as process:
      try:
          for line in process.stdout:
              ...
      except (KeyboardInterrupt, OSError):
          process.kill()
          process.wait()
          raise
  ```
- The partial `output_lines` buffer is lost in this case; `fastchess.log` will not be
  written since the exception propagates up to `run_forever()`'s handler.

### Console output failure

If `Console.status` raises `OSError` (e.g., broken pipe from closed terminal), the `Popen`
context manager still cleans up the child process. The exception propagates to
`run_forever()`'s exception handler (line 277 in `client.py`), which logs the error and
reports a failed job to the server. Note: `fastchess.log` will not be written in this case
since the exception exits the loop before the log-write step.

### No change to non-verbose error paths

When verbose is False, `console.status` is never called during the loop, so `OSError` from
`print` cannot occur. The accumulated `log_text` and return-code check produce identical
results to today's `subprocess.run(capture_output=True)`.

## Testing Strategy

**Note:** The project has no existing test files but uses pytest conventions (`.pytest_cache`
in `.gitignore`). These test cases describe what should be verified.

### Unit tests for `MatchRunner`

1. **Verbose mode streams output**: Mock `subprocess.Popen` to yield known lines from
   stdout. Assert `console.status` is called once per line with tag `"FC"` and the correct
   stripped content.

2. **Quiet mode does not print**: Same Popen mock with `verbose=False`. Assert
   `console.status` is never called with tag `"FC"`.

3. **Log text captured in both modes**: Assert that the returned `log_text` (used for
   `fastchess.log`) contains all output lines regardless of the verbose setting.

4. **Non-zero return code raises RuntimeError**: Mock `Popen` to return a non-zero exit
   code. Assert `RuntimeError` is raised with the accumulated output as the message.

5. **Empty output with non-zero code**: Mock `Popen` with no stdout lines and return code
   1. Assert the error message includes the return code number.

6. **Process killed on KeyboardInterrupt**: Mock `Popen` and raise `KeyboardInterrupt`
   during line iteration. Assert `process.kill()` and `process.wait()` were called.

### Unit tests for `Console` thread safety

7. **Multi-line section not interrupted**: Spawn two threads — one calling
   `console.section(...)` in a tight loop and another calling `console.status(...)`.
   Capture stdout and verify that no `status` line appears between the heading and
   key-value rows of any `section` call.

8. **Concurrent access completes without deadlock**: Spawn multiple threads each calling
   `console.section(...)` and `console.status(...)` concurrently, with a timeout. Assert
   all threads complete within the timeout (catches accidental deadlock from a reentrant
   lock mistake).

### Integration test

9. **Flag plumbing**: Construct `MatchRunner` directly with `verbose=True` and a mock
   `Console`. Verify that `self.verbose` is set correctly. Separately, verify that
   `build_parser().parse_args(["--server", "x", "--access-key", "x", "--threads", "1",
   "--hash", "1", "-v"])` produces `args.verbose == True`.

### Edge cases

10. **Fastchess produces no output**: Popen stdout yields zero lines. Assert `log_text` is
    empty, and the PGN-missing check (`RuntimeError("fast-chess did not produce a PGN
    file.")`) still triggers.

11. **Non-UTF8 output**: `Popen` uses `text=True` which defaults to UTF-8. Consider adding
    `errors="replace"` to the `Popen` call to gracefully handle binary output from a
    misbehaving engine, rather than crashing with `UnicodeDecodeError`.
