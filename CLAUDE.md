# PM-Email-Chat

Voice note in, reviewed email out, sent from the user's Zoho mailbox.

When the user sends a voice note or dictated text asking for an email, follow
`.claude/skills/vn-email/SKILL.md`. The short version:

1. `python3 -m pmail parse --vn "<transcript>"` — see who it resolves to.
2. Write the email prose yourself; the parser only extracts routing.
3. `python3 -m pmail draft new --vn "<transcript>" --subject ... --body-file ...`
4. Show the full preview in chat and wait for an explicit yes.
5. `python3 -m pmail send <id> --confirm`

## Transport, by where the session runs

From a **cloud session** SMTP is impossible — the sandbox routes only HTTPS, so
`PMAIL_TRANSPORT=api` is the only option and the environment must allowlist
`mail.zoho.<tld>` and `accounts.zoho.<tld>`. From a **local** checkout, SMTP with
an app password works fine. `python3 -m pmail doctor --live` checks the network
path first and prints the fix; trust it rather than retrying a hanging send.

## Non-negotiables

- **Approval per email, in the current turn.** Never treat a past "yes", or a
  general "you can send my emails", as permission to send this one.
- **Never invent an email address.** Addresses come from `contacts.json` or
  from the transcript. An unrecognised name is a question for the user. A
  company name identifies *which* person, never their address — "Sara from
  RE/MAX" still needs her address supplied once, then it is saved.
- **Never claim something was sent unless the command succeeded.** Report the
  real error otherwise.

## Layout

| Path | What it is |
| --- | --- |
| `pmail/` | The tool. Python 3.9+, standard library only — no install step. |
| `pmail/transcript.py` | Heuristics that pull routing out of dictation. |
| `pmail/contacts.py` | Address book. The only source of email addresses. |
| `pmail/message.py` | MIME building and the validation guards. |
| `pmail/senders/` | `smtp.py` (default) and `zoho_api.py` (OAuth). |
| `pmail/net.py` | Reachability probes that turn a hang into a named fix. |
| `contacts.json` | The user's address book. **Commit changes to it.** |
| `history/sent.jsonl` | Audit log of everything sent. **Committed.** |
| `drafts/` | Scratch. Gitignored — drafts do not survive the session. |
| `tests/` | `python3 -m unittest discover -s tests -t .` |

## Persistence

This runs in an ephemeral container. Anything not committed is gone next
session. After adding contacts or sending mail, commit `contacts.json` and
`history/sent.jsonl`.

Credentials are the exception: they live in environment variables (or a
gitignored `.env`) and must never be committed. If a credential ever lands in
a commit, say so immediately — it has to be rotated in Zoho, not just removed.

## Conventions

- Standard library only. Do not add dependencies without asking.
- Every new guard in `message.py` needs a test in `tests/test_message.py`.
- Run the suite before committing; it takes under a second.
