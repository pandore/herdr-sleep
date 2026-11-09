# herdr-sleep

A [Herdr](https://herdr.dev) plugin that puts Claude Code agents to sleep after a day of silence and leaves a summary page in their tab. One Enter brings the same conversation back, in the same folder, with the same launch flags and permission mode.

An idle Claude Code agent still holds its process and every MCP server it started: typically 0.3–0.6 GB. With 15 agents waiting for you, that is several gigabytes and a full swap. herdr-sleep frees that memory without losing anything, and when you come back to a tab you can see in ten seconds what was going on there.

> **Status: beta.** Built and tested on one Apple Silicon Mac with Herdr 0.9.1 and Claude Code 2.1. The page and the summaries are in **Ukrainian**. Expect rough edges on other setups — issues and PRs welcome.

## What a sleeping tab looks like

The tab label gets a 💤, the sidebar keeps a `sleeping` row for the pane, and the pane shows:

```text
💤 build-blog-owner спить з 09.11 13:40   ~/Repos/blog

Проєкт · Personal / Blog
  Що: особистий блог на Astro з нотатками про AI-агентів і щотижневою розсилкою.
  Агент: власник проєкту; веде сайт і контент, публікує лише після «так».

Про що
  Я додав RSS і сторінку архіву, збірка проходить. Не опубліковано: чекаю, де хостити.
  Від тебе потрібне рішення щодо хостингу й домену.

Останні дії · 03.11
  17:18  ✚ створено src/pages/rss.xml.ts, src/pages/archive.astro
  17:21  ✎ змінено astro.config.mjs
  17:21  ▸ Build the site and check internal links
  18:25  › ти: «а що з доменом?»
  18:25  ◦ переглянуто package.json
  18:27  ? питання тобі: Хостимо на Vercel чи на Netlify?

Твоє останнє повідомлення
  а що з доменом?

Остання відповідь агента
  Домен поки не підключав. Для Vercel потрібен лише CNAME …

Enter — продовжити з того самого місця
Вручну: cd ~/Repos/blog && claude --effort high --permission-mode auto --resume 0b6f…
```

- **Проєкт** (project): where the tab lives and two lines on what the project is and the agent's role, written by Haiku from the brief the agent started with and the project's `CLAUDE.md` / `AGENTS.md` / `README.md`.
- **Про що** (what it was about): 3–5 lines by Haiku from the end of the conversation. Without Haiku, Claude's own `※ recap` is shown.
- **Останні дії** (last actions): the last 8 things that happened, read straight from the transcript — files created (✚) and changed (✎), commands (▸, Claude's own description of each), your messages (›), questions to you (?), subagents and messages to other agents (⇢), web searches (⌕). Runs of the same kind merge into one line.
- Your last message and the agent's last reply.

The page fits the pane: when it is short, the agent's reply shrinks first and the last actions last. Typing text and pressing Enter does not send it anywhere; only an empty Enter wakes the agent.

## How it works

Every hour a small watcher looks at `herdr agent list`. A Claude agent goes to sleep only when **all** of this holds; anything uncertain keeps it awake:

- its status is `idle` or `done`, and neither its pane nor its tab is focused;
- its last real message (yours or the agent's) is older than the threshold — not the file's modification time, because Claude appends bookkeeping to quiet sessions;
- Herdr knows its session id, the transcript exists and belongs to the pane's folder, and the session is not open in another pane;
- the `claude` process is a child of the pane's shell, and its launch flags are ones we know how to replay (unknown options, `-p`, `--fork-session`, an initial prompt → stays awake);
- it runs no background command (children other than MCP or language servers);
- the composer is empty — dim text is Claude's suggestion and does not count, anything you typed does;
- its folder is not excluded in the config.

Then it:

1. writes the summaries (two short Haiku calls through your own `claude` CLI, with hooks, tools and MCP servers off and no session saved), and checks everything again;
2. copies the transcript to `~/.local/state/herdr-sleep/transcripts/` (Claude deletes transcripts untouched for 30 days) and writes a record with the exact resume command;
3. sends `SIGTERM` to `claude`, which exits cleanly and takes its MCP servers along — never `SIGKILL`; if it is still running after 30 s the record is dropped and the agent stays;
4. claims the pane in the sidebar, adds 💤 to the tab label and starts the page in the pane's shell.

Enter on the page checks the session is not open elsewhere, restores the transcript from the backup if Claude deleted it, and `exec`s `claude <same flags> --permission-mode <mode before sleep> --resume <id>` in the same folder. The agent gets its Herdr name back and the 💤 goes away. After a Herdr restart, the startup hook draws the pages again in panes that came back as plain shells.

## Requirements

- Herdr 0.9.1 or newer, on macOS (Linux is untested).
- Herdr's Claude integration: `herdr integration install claude` — that is how Herdr learns each pane's session id.
- Python 3.9+ (the system `/usr/bin/python3` is fine; standard library only).
- A logged-in `claude` CLI on the PATH for the Haiku summaries. Each sleep costs two short Haiku requests on your plan, and the end of the conversation is sent to Anthropic, as in the session itself. Set `"summary_model": ""` to turn this off.

## Install

```bash
herdr plugin install pandore/herdr-sleep
```

The watcher starts on the next tab switch (or when the Herdr server next starts) and sleeps every agent that already qualifies. To see first what it would do, run `./herdr-sleep preview` in the plugin folder (`herdr plugin list` shows where it is).

## Settings

Optional, in `~/.config/herdr-sleep/config.json`:

```json
{
  "idle_hours": 24,
  "poll_seconds": 3600,
  "exclude_cwds": ["~/agents/orchestrator"],
  "brief_dirs": ["~/agents/briefs"],
  "summary_model": "haiku",
  "user_name": "Олена"
}
```

- `exclude_cwds`: agents running in these folders never sleep (for example an orchestrator you always want to answer at once).
- `brief_dirs`: where briefs the agents start from may live; the project summary reads a `.md` named in the agent's first messages only from these folders or the project itself.
- `user_name`: lets the summaries call you by name.

An unreadable file, an unknown key or a wrong type turns sleeping off (logged in `~/.local/state/herdr-sleep/sleep.log`) rather than ignoring an exclusion. After changing the file, stop the watcher (`kill $(cat ~/.local/state/herdr-sleep/watcher.pid)`); the next tab switch starts it with the new settings.

## Commands

The script doubles as a CLI:

```text
herdr-sleep preview           each agent and why it would or would not sleep (changes nothing)
herdr-sleep sleep-pane PANE   sleep one agent now (skips the quiet-time and focus checks)
herdr-sleep list              sleeping sessions and their manual resume commands
herdr-sleep refresh           redraw every sleeping page with the current code
herdr-sleep sweep             one pass now
```

To wake a pane from a script or another agent: `herdr pane send-keys <pane> enter`.

## Limits

- Claude Code only. Other agent kinds are left alone.
- Depends on Herdr's CLI fields (`agent_session`, `foreground_cwd`, `state_change_seq`) and on Claude Code's transcript format and footer text; a change there makes agents stay awake, not break.
- A small window remains between the last check and `SIGTERM`; Claude discards an unsent draft on exit, which is why a non-empty composer is a hard stop.
- The project lines are written when the agent falls asleep and do not follow later changes to the project.
- Command lines in "Останні дії" are in whatever language Claude wrote their descriptions in (usually English).

## Tests

```bash
python3 -m unittest test_herdr_sleep
```

## Credits

Ideas came from the existing community plugins: [herdr-sleeper](https://github.com/djbclark/herdr-sleeper) (fail-closed checks, `SIGTERM` exit), [herdr-park](https://github.com/prabhatCH/herdr-park) (sidebar claim, the Enter stub) and [herdr-idle](https://github.com/DnzzL/herdr-idle) (background-command check). No code was copied.

## License

MIT
