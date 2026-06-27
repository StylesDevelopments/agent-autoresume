# claude-autoresume

[![CI](https://github.com/StylesDevelopments/claude-autoresume/actions/workflows/ci.yml/badge.svg)](https://github.com/StylesDevelopments/claude-autoresume/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](./LICENSE)
[![Shell](https://img.shields.io/badge/shell-bash-green.svg)](./claude-autoresume.sh)
[![iTerm2](https://img.shields.io/badge/iTerm2-Python%20API-blueviolet.svg)](./iterm/claude-limit-watcher.py)

**Stop babysitting AI coding-agent usage limits.** When [Claude Code](https://www.claude.com/product/claude-code) or [Codex](https://github.com/openai/codex) hits your limit it just *stops* and waits for you to come back and resubmit — neither has a built-in resume. This repo gives you two small, dependency-free tools that wait out the limit and pick the work back up for you.

> Unofficial community tool. Not affiliated with or endorsed by Anthropic.

Supports **Claude Code** and **Codex**.

| Tool | For | Terminal | You run the agent… |
|---|---|---|---|
| **iTerm2 live watcher** | Interactive sessions | iTerm2 | exactly as you do now |
| **tmux live watcher** | Interactive sessions | **any** (Terminal.app, iTerm2, Ghostty…) | inside `tmux`, as normal |
| **Headless wrapper** | Unattended one-shot / overnight jobs | any | via a wrapper command |

Pick whichever matches how you work — or use several.

---

## 1. iTerm2 live watcher (recommended for interactive use)

A tiny background daemon (iTerm2's Python API) that watches your terminal sessions. It supports **both Claude Code and Codex**. When it sees a limit banner —

```
You've hit your session limit · resets 3:45pm            (Claude Code)
You've hit your weekly limit · resets Mon 12:00am        (Claude Code)
You've hit your usage limit. … or try again at 3:45 PM.  (Codex)
```

— it parses the reset time, **waits until then**, and types a clearly-visible resume banner (`** USAGE LIMIT RESET, RESUME SESSION **` by default) into that exact session. **You keep launching `claude` / `codex` exactly as you always do**; the watcher just sits in the background and nudges them on when the limit lifts.

Both tools' fullscreen/alternate-screen renderers are handled (Codex defaults to alt-screen; Claude Code's `/tui fullscreen` is the same idea) — iTerm2's API reads the rendered grid either way.

It reads the rendered screen as plain text and sends keystrokes through iTerm2's own API socket — so it needs **no macOS Accessibility or screen-recording permission**, just the iTerm2 Python API.

### Install

```bash
curl -fsSL https://raw.githubusercontent.com/StylesDevelopments/claude-autoresume/main/iterm/install-iterm.sh | bash
```

Then two one-time manual steps (macOS won't let a script do these for you):

1. **Enable the API:** iTerm2 → Settings → General → Magic → check **"Enable Python API"**.
2. **Start it:** iTerm2 menu bar → **Scripts → AutoLaunch → `claude-limit-watcher.py`** (it also auto-starts on every future iTerm2 launch).

Watch it work:

```bash
tail -f ~/.claude/iterm-limit-watcher.log
```

### Test it safely first

Before letting it send real keystrokes, run it in **dry-run** — it logs *"would send …"* but sends nothing:

```bash
launchctl setenv CLAUDE_RESUME_DRY_RUN 1
# fully quit & reopen iTerm2 so the daemon picks up the env var
# undo later with:  launchctl unsetenv CLAUDE_RESUME_DRY_RUN
```

Hit a limit (or wait until you naturally do), confirm the log shows it detected the banner and parsed the right reset time, then turn dry-run off.

### Configuration

Set these for the GUI app with `launchctl setenv NAME value`, then restart iTerm2:

| Variable | Default | What it does |
|---|---|---|
| `CLAUDE_RESUME_TEXT` | `** USAGE LIMIT RESET, RESUME SESSION **` | What it types to resume a session |
| `CLAUDE_RESUME_DRY_RUN` | `0` | `1` = log what it would do, send nothing |
| `CLAUDE_RESUME_CUSHION` | `8` | Seconds to wait *past* the reset time before sending |
| `CLAUDE_RESUME_MAX_WAIT` | `28800` | Safety cap on how long it will wait (8h) |
| `CLAUDE_RESUME_FALLBACK` | `900` | If the reset time can't be parsed, retry after this many seconds |
| `CLAUDE_RESUME_MATCH` | `""` | Only watch sessions whose command matches this substring; empty = all |
| `CLAUDE_RESUME_LOG` | `~/.claude/iterm-limit-watcher.log` | Log file path |

### Fullscreen mode (`/tui fullscreen`)

Claude Code's fullscreen renderer (the v2.1.89+ preview, toggled with `/tui fullscreen`) draws on the terminal's **alternate screen buffer**, like `vim` or `htop`. The watcher handles **both** renderers:

- **Fullscreen / alt-screen:** the banner stays on the rendered grid until Claude repaints, so it's actually *easier* to detect reliably.
- **Default / inline:** the banner prints into normal scrollback and can scroll off — so the watcher captures the reset time **the first time it sees it** and schedules the resume immediately.

Either way it reads the rendered cell grid (already plain text, no ANSI), rejoins soft-wrapped lines, and debounces so spinners/redraws don't cause double-fires.

### How it works / caveats

- One screen-streamer per session (event-driven, no busy-polling). When the banner matches, it arms a single resume and re-arms only after the banner clears — so it never double-fires on one limit.
- Before sending, it **re-checks the screen** — if you already came back and resumed, it skips.
- It's screen-scraping, so it depends on Claude Code's banner wording. If that ever changes, tune `LIMIT_RE` at the top of [`claude-limit-watcher.py`](./iterm/claude-limit-watcher.py). The reset-time parser is covered by [`test_limit_watcher.py`](./iterm/test_limit_watcher.py) (`python3 iterm/test_limit_watcher.py`).
- It resumes what's *resumable*: a stalled agentic task nudged with `continue` carries on; a session idling for your next instruction has nothing meaningful to auto-continue.

> **Alternative (no daemon): iTerm2 Triggers.** iTerm2 can fire an action on a regex match (Profiles → Advanced → Triggers). You can wire a trigger on `You've hit your .*limit .*resets (.+)` to **Invoke Script Function** and hand the captured time + session to a registered RPC. The bundled daemon is more self-contained (no per-profile setup), so it's the default here — but the trigger route works if you prefer iTerm2's native feature.

---

## 2. tmux live watcher (any terminal, incl. Terminal.app)

Prefer Terminal.app, Ghostty, or anything that isn't iTerm2? Run your agent inside **tmux** and use this watcher. It polls every tmux pane, detects the same Claude Code / Codex banners, and resumes with `send-keys`.

Why tmux: `capture-pane` reads the live rendered screen (including fullscreen/alt-screen TUIs) and `send-keys` drives a running TUI — with **zero macOS Automation/Accessibility permissions**. The only ask: launch your agent inside tmux.

### Install

```bash
curl -fsSL https://raw.githubusercontent.com/StylesDevelopments/claude-autoresume/main/tmux/install-tmux.sh | bash
```

Needs `tmux` (`brew install tmux`) and `python3`.

### Usage

```bash
# 1. Work inside tmux and run your agent there as normal:
tmux
claude          # ...or: codex

# 2. In any shell, leave the watcher running:
claude-autoresume-tmux
# or in the background:
nohup claude-autoresume-tmux >/dev/null 2>&1 &
tail -f ~/.claude/tmux-limit-watcher.log
```

Test safely first (logs what it would do, sends nothing):

```bash
CLAUDE_RESUME_DRY_RUN=1 claude-autoresume-tmux
```

### Configuration

Environment variables: `CLAUDE_RESUME_TEXT` (the obvious banner), `CLAUDE_RESUME_DRY_RUN` (`0`), `CLAUDE_RESUME_POLL` (`20`s between scans), `CLAUDE_RESUME_CUSHION` (`8`), `CLAUDE_RESUME_MAX_WAIT` (`28800`), `CLAUDE_RESUME_FALLBACK` (`900`), `CLAUDE_RESUME_LOG`, `CLAUDE_RESUME_TMUX`.

It's polling-based (every `CLAUDE_RESUME_POLL` seconds) rather than event-driven like the iTerm2 watcher — tmux has no screen-change push — but the overhead is negligible and the detection logic is the exact same shared module.

---

## 3. Headless wrapper (for unattended jobs)

For "go do this big job on your own and resume across limits," run Claude Code through the wrapper instead of directly. On a limit it waits and resumes the **same session** with `--continue`, until the job is done. Non-limit errors fail fast so a genuine bug doesn't loop.

### Install

```bash
curl -fsSL https://raw.githubusercontent.com/StylesDevelopments/claude-autoresume/main/install.sh | bash
```

Installs `claude-autoresume` into `~/.local/bin`. Or download [`claude-autoresume.sh`](./claude-autoresume.sh) manually and put it on your `PATH`.

### Usage

```bash
# Run a task and auto-resume across limits
claude-autoresume "Refactor the auth module onto the service layer"

# Fire-and-forget overnight
nohup claude-autoresume "big task" >/dev/null 2>&1 &
tail -f ~/.claude/autoresume.log
```

| Outcome each round | Action |
|---|---|
| `exit 0` | Turn finished. **Stop** (unless `KEEP_GOING=1`). |
| `exit != 0` + limit/rate/overload message | **Wait `INTERVAL`, resume.** Indefinitely. |
| `exit != 0` + any other error | Retry up to `MAX_ERRORS`, then give up. |

Config via env vars: `INTERVAL` (300), `ERROR_WAIT` (15), `MAX_ERRORS` (3), `RESUME` (0), `KEEP_GOING` (0), `MAX_STALL` (25), `LOG`, `CLAUDE_BIN`. Run `claude-autoresume --help` for details.

For a long multi-turn job, set `KEEP_GOING=1`: the wrapper keeps nudging after each clean exit and only stops when the agent prints `<<TASK_COMPLETE>>` (or after `MAX_STALL` empty rounds).

---

## Why this exists

Claude Code has no native "wait for my limit to reset and carry on" feature ([#36320](https://github.com/anthropics/claude-code/issues/36320), [#35744](https://github.com/anthropics/claude-code/issues/35744), [#46959](https://github.com/anthropics/claude-code/issues/46959)). There's no hook, setting, or plugin that fires on a usage limit and resumes — the only paths are an external wrapper or an external watcher, which is exactly what's here.

> The truly native way to *not stop at all* is to enable **extra usage / overage billing** on your account, so Claude Code doesn't hard-stop at the included limit. That's a billing setting, not something a script can do — but if you'd rather pay than wait, that's the real fix.

## FAQ

**Does the watcher need Accessibility permission?** No — it uses iTerm2's API socket, not synthetic keystrokes, so it skips the Accessibility/Screen-Recording prompts that AppleScript `keystroke` or `cliclick` need. Only "Enable Python API" in iTerm2.

**Will it loop forever on a broken task?** The wrapper only retries *limit* failures indefinitely; other errors stop after `MAX_ERRORS`. The watcher only acts on the specific limit banner and re-checks before sending.

**Other terminals (Terminal.app, Ghostty…)?** Use the **tmux live watcher** (section 2) — it works in any terminal as long as you run the agent inside tmux. The iTerm2 watcher is only for iTerm2.

**Codex too?** Yes — both live watchers detect Codex's `You've hit your usage limit … try again at …` banner (incl. cross-day dates and `try again later`) alongside Claude Code's.

## Development

```bash
python3 tests/test_limit_detect.py     # detection + reset-time parsing (Claude + Codex)
python3 iterm/test_limit_watcher.py    # iTerm soft-wrap reconstruction + import wiring
bash    tests/test_tmux_integration.sh # end-to-end: real tmux pane, real resume
```

CI ([`.github/workflows/ci.yml`](./.github/workflows/ci.yml)) runs all of the above plus `bash -n` and `py_compile` on every push and PR. The integration test is the key one — it spins up a real tmux pane, shows a real limit banner, runs the watcher for real, and asserts it types the resume text into the pane.

## License

MIT — see [LICENSE](./LICENSE).
