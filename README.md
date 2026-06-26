# claude-autoresume

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](./LICENSE)
[![Shell](https://img.shields.io/badge/shell-bash-green.svg)](./claude-autoresume.sh)

**Keep a [Claude Code](https://www.claude.com/product/claude-code) job alive across usage-limit resets.** When Claude Code stops because you hit your 5-hour or weekly limit, this tiny, dependency-free bash wrapper waits and resumes the same session automatically — so a long job picks itself back up the moment your limit lifts, without you sitting there to restart it.

> Unofficial community tool. Not affiliated with or endorsed by Anthropic.

## The problem

Claude Code has no built-in "wait for my limit to reset and carry on" feature ([#36320](https://github.com/anthropics/claude-code/issues/36320), [#35744](https://github.com/anthropics/claude-code/issues/35744)). When you hit a usage limit mid-task, the session hard-stops and you have to come back and restart it by hand. That's fine at your desk — useless for an overnight job.

`claude-autoresume` runs Claude Code headlessly and, on a limit, waits and resumes — indefinitely — until the work is done. Real errors (not limits) still fail fast so a genuine bug doesn't loop forever.

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/StylesDevelopments/claude-autoresume/main/install.sh | bash
```

This drops the script in `~/.local/bin`. If that's not on your `PATH`, the installer tells you how to add it.

**Or manually** — download [`claude-autoresume.sh`](./claude-autoresume.sh), make it executable, and put it anywhere on your `PATH`:

```bash
curl -fsSL https://raw.githubusercontent.com/StylesDevelopments/claude-autoresume/main/claude-autoresume.sh -o ~/.local/bin/claude-autoresume
chmod +x ~/.local/bin/claude-autoresume
```

Requires `bash`, `claude` on your `PATH`, and `curl` or `wget`.

## Usage

```bash
# Run a task and auto-resume across limits
claude-autoresume "Refactor the auth module onto the service layer"

# Resume the last session and nudge it forward
claude-autoresume

# Fire-and-forget: leave it running unattended and watch the log
nohup claude-autoresume "big overnight task" >/dev/null 2>&1 &
tail -f ~/.claude/autoresume.log
```

### What it does each round

| Outcome | Action |
|---|---|
| `exit 0` | The turn finished. **Stop** (unless `KEEP_GOING=1`). |
| `exit != 0` + a limit/rate/overload message | **Wait `INTERVAL`, then resume.** Indefinitely. |
| `exit != 0` + any other error | Retry up to `MAX_ERRORS` times, then give up. |

## Configuration

Everything is tuned with environment variables — no config file:

| Variable | Default | What it does |
|---|---|---|
| `INTERVAL` | `300` | Seconds to wait after a limit hit before resuming |
| `ERROR_WAIT` | `15` | Seconds to wait between non-limit retries |
| `MAX_ERRORS` | `3` | Consecutive non-limit failures before bailing |
| `RESUME` | `0` | `1` = add `--continue` on the very first run too |
| `KEEP_GOING` | `0` | `1` = keep nudging until the agent signals completion (see below) |
| `MAX_STALL` | `25` | `KEEP_GOING`: max `exit 0`-without-signal rounds before stopping |
| `LOG` | `~/.claude/autoresume.log` | Log file path |
| `CLAUDE_BIN` | `claude` | Path to the `claude` binary |
| `LIMIT_REGEX` | *(built-in)* | Override the limit-detection regex (advanced) |

```bash
# Poll every 2 minutes instead of 5
INTERVAL=120 claude-autoresume "task"

# Keep going across many turns for a large job
KEEP_GOING=1 claude-autoresume "migrate the whole test suite to Vitest"
```

## The one honest caveat

In Claude Code's headless mode, **`exit 0` means "the agent finished its turn"** — which isn't always the same as "the whole job is done." For a small, single-turn task that's exactly right, and the default behaviour (stop on `exit 0`) is what you want.

For a big multi-hour job, set **`KEEP_GOING=1`**. The wrapper then keeps nudging the agent to continue after each clean exit and only stops when the agent prints the sentinel `<<TASK_COMPLETE>>` — or after `MAX_STALL` empty rounds, as a safety net. It's the closest you can get to truly unattended large jobs given Claude Code has no native "task complete" signal.

## How it works

It's ~120 lines of bash. Each round it runs `claude` headlessly (`-p`, plus `--continue` to resume), captures the output, and inspects the exit code:

- **`exit 0`** → done (or, with `KEEP_GOING`, nudge on).
- **non-zero + output matching `LIMIT_REGEX`** → treat as a usage/rate limit, sleep `INTERVAL`, resume.
- **non-zero + anything else** → count it as a real failure; after `MAX_ERRORS` in a row, stop.

After the first attempt it always resumes with `--continue`, so a task that spans several limit windows is picked up where it left off rather than restarted. Everything is logged to `~/.claude/autoresume.log`.

## FAQ

**Does it use extra API credits while waiting?** Only the retry attempts. Each retry after a limit is one quick call that fails immediately — that's why the default `INTERVAL` is 5 minutes rather than seconds. The limit only lifts at its reset time, so polling faster just wastes failed calls.

**Will it loop forever on a broken task?** No. Only *limit* failures retry indefinitely. Any other error retries `MAX_ERRORS` times (default 3) and then exits.

**Does it work with a `claude` subscription and with API keys?** Yes — it doesn't care how you're authenticated; it just reruns `claude` and reacts to the result.

## License

MIT — see [LICENSE](./LICENSE).
