# Contributing

Thanks for helping with nfl-stat-cli. Please run the tests before opening a pull request:

```bash
python -m pip install -e . pytest
python -m pytest -q
```

## Keep personal details out of the repository

This is a public repository, and git history is public and permanent.

- **Commit with a noreply or project address**, not a personal inbox:
  `git config user.email "<id>+<username>@users.noreply.github.com"` (GitHub: *Settings -> Emails -> Keep my email addresses private*).
- **Do not commit local machine paths** (home directories, usernames, drive layouts). Read locations from environment variables or configuration instead.
- **Do not commit keys, tokens or credentials**, and do not paste them into issues, commit messages or pull request text.
- `tests/test_privacy_hygiene.py` fails if a free-mail address or an absolute path containing an account name appears in the tracked tree.

Existing history is intentionally not rewritten; the checks above apply to new commits and to the current tree.
