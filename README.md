# agent-autoresume

[![CI](https://github.com/StylesDevelopments/agent-autoresume/actions/workflows/ci.yml/badge.svg)](https://github.com/StylesDevelopments/agent-autoresume/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](./LICENSE)

**Stop babysitting AI coding-agent usage limits.** When [Claude Code](https://www.claude.com/product/claude-code) or [Codex](https://github.com/openai/codex) hits your 5-hour / weekly limit it just stops and waits for you to resubmit. These small, dependency-free tools wait out the limit and resume the work for you.

> Unofficial. Not affiliated with Anthropic or OpenAI.

## Which one?

| Tool | When | Setup |
|---|---|---|
| **iTerm2 watcher** | You use iTerm2 | install once → runs forever |
| **tmux watcher** | Any terminal (Terminal.app, Ghostty…) | install once → runs forever |
| **headless wrapper** | Unattended one-shot / overnight jobs | run a command |

The two watchers are **set-and-forget**: install once, they auto-start at login and resume your sessions whenever a limit lifts. You keep running `claude` / `codex` exactly as normal. Both support Claude Code **and** Codex.

## Install

**iTerm2:**
```bash
curl -fsSL https://raw.githubusercontent.com/StylesDevelopments/agent-autoresume/main/iterm/install-iterm.sh | bash
```
Then enable iTerm2 → Settings → General → Magic → **Enable Python API** and start it once from **Scripts → AutoLaunch** (it auto-starts every launch after that).

**Terminal.app / any terminal (tmux):**
```bash
curl -fsSL https://raw.githubusercontent.com/StylesDevelopments/agent-autoresume/main/tmux/install-tmux.sh | bash
```
Installs a launchd login agent that runs forever. Just run your agents inside `tmux`. Needs `tmux` + `python3`.

**Headless wrapper** (unattended jobs):
```bash
curl -fsSL https://raw.githubusercontent.com/StylesDevelopments/agent-autoresume/main/install.sh | bash
agent-autoresume "big task"            # Claude Code
agent-autoresume --codex "big task"    # Codex
```

## How it works

A watcher reads your terminal screen, spots a blocking limit banner (`You've hit your … limit · resets 3:45pm`, `… resets in 1d 5h`, or Codex `… try again at 3:45 PM`), waits until the reset, then types a clear marker — `** USAGE LIMIT RESET, RESUME SESSION **` — back into that session. If Claude shows its interactive limit menu, the watcher selects the highlighted `Stop and wait for limit to reset` option. The iTerm2 watcher uses iTerm2's API; the tmux watcher uses `capture-pane`/`send-keys` — **neither needs macOS Accessibility/screen-recording permission**.

Claude Code statuslines can also show a non-blocking quota footer such as `Usage ⚠ Limit reached (resets in 1d 5h)` while requests still work. The watchers intentionally ignore that footer by itself and wait for an actual blocked-turn banner before resuming.

Tune via env vars (see each script's header or `--help`). Test safely first with `AUTORESUME_DRY_RUN=1` (logs what it would do, sends nothing).

**Caveat:** it's screen-scraping, so it depends on the banner wording — if a tool changes it, that's a one-line regex tweak in [`limit_detect.py`](./limit_detect.py) (covered by tests + CI).

## Develop

```bash
python3 tests/test_limit_detect.py        # detection + reset-time parsing
python3 iterm/test_limit_watcher.py       # iTerm soft-wrap + import wiring
bash    tests/test_tmux_integration.sh    # end-to-end: real tmux pane, real resume
```
CI runs all of the above (plus `bash -n`, `py_compile`, shellcheck) on every push and PR.

## License

MIT — see [LICENSE](./LICENSE).
