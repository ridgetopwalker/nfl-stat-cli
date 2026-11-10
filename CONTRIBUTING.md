# Contributing

Thanks for helping with pro-football-slm. Please run the tests before opening a pull request:

```bash
python -m venv .venv && . .venv/bin/activate   # Windows: .venv\Scripts\activate
python -m pip install -e . pytest
python -m pytest -q
```

## Keep personal details out of the repository

This is a public repository, and git history is public and permanent.

- **Commit with a noreply or project address**, not a personal inbox. For this repository only (no `--global`):
  `git config user.email "<id>+<username>@users.noreply.github.com"`.
  On GitHub, turn on *Settings -> Emails -> Keep my email addresses private* and *Block command line pushes that expose my email*; those settings are what actually enforce it for new commits.
- **Do not commit local machine paths** (home directories, usernames, drive layouts). Read locations from environment variables or configuration instead.
- **Do not commit keys, tokens or credentials**, and do not paste them into issues, commit messages or pull request text.
- `tests/test_privacy_hygiene.py` fails if a free-mail address or an absolute path containing an account name appears in the tracked tree (placeholders such as `<user>` are allowed, and one folder that is being reworked is temporarily exempt, see the test). It checks files, not commit metadata.

Existing history is intentionally not rewritten.
