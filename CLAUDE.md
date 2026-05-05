# Working with the OdooAPPS repository

## Audience note

The primary user of this repository is **not a developer**. They rely on
explicit, step-by-step instructions for anything that happens in the terminal.

## After every change that is committed and pushed

Always finish the turn with a short "How to see this live" block that covers:

1. Stopping the running Flask process (Ctrl+C in its terminal).
2. The exact `git pull` command for the current branch.
3. `pip install -r requirements.txt` if dependencies changed — otherwise
   explicitly say "no new dependencies, skip pip install".
4. The exact command to restart Flask (`python app.py`).
5. A reminder to hard-refresh the browser (Ctrl+Shift+R / Cmd+Shift+R) so new
   CSS/JS aren't served from cache.
6. If the change added diagnostic logging, point out what log line to watch for
   and what it would mean.

Keep it a plain numbered list with commands in code fences. No "if you know
what you're doing" shortcuts, no assumed context.

## Development branches

Long-lived development happens on branches of the form
`claude/continue-development-<suffix>`. Push to that branch; never to `main`
unless the user explicitly asks.
