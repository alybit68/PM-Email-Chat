# PM-Email-Chat

Send a voice note, get an email — drafted for review, then sent from your Zoho
mailbox.

You dictate something like *"email Sara and the dev team that the release
slipped to Friday, cc finance"*. Claude resolves the names against your address
book, writes the actual email, shows you the full draft, and sends it only
after you say yes.

Python 3.9+, standard library only. Nothing to install.

---

## Setup

### 1. Get a Zoho credential

**SMTP (recommended — simplest).** In Zoho Mail go to
**My Account → Security → App Passwords** and generate one for "PM-Email-Chat".
An app-specific password is required when two-factor auth is on, and is worth
using either way: it is scoped and revocable without touching your login.

**REST API (alternative).** If SMTP is disabled on your account, create a Self
Client at <https://api-console.zoho.com> with scopes
`ZohoMail.messages.CREATE,ZohoMail.accounts.READ` and generate a refresh token.
Set `PMAIL_TRANSPORT=api`.

### 2. Set your environment variables

For Claude Code on the web, set these in your **environment settings** so they
survive container restarts. Locally, copy `.env.example` to `.env`.

```bash
ZOHO_EMAIL=you@yourdomain.com
ZOHO_FROM_NAME=Your Name
ZOHO_APP_PASSWORD=<the app password>
ZOHO_REGION=us               # us | eu | in | au | jp | ca | sa
ZOHO_ACCOUNT_TYPE=personal   # 'organization' for paid custom-domain plans
PMAIL_ALLOW_SEND=1           # master switch; leave unset to force dry runs
```

`ZOHO_REGION` must match the data centre your mailbox lives in — check the
domain you sign in at (zoho.com, zoho.eu, zoho.in…). `ZOHO_ACCOUNT_TYPE`
selects the host: `personal` → `smtp.zoho.<tld>`, `organization` →
`smtppro.zoho.<tld>`.

Verify:

```bash
python3 -m pmail doctor --live
```

`--live` authenticates against Zoho and disconnects. It sends nothing.

### 3. Fill in your address book

This is what lets a voice note say "Sara" instead of an address.

```bash
python3 -m pmail contacts add --key sara --name "Sara Diaz" \
  --email sara.diaz@example.com --aliases "sara d" --groups dev-team
```

See `contacts.example.json` for the file format, including groups. **Commit
`contacts.json`** — the container is wiped between sessions.

---

## Using it

Just send the voice note in chat. Claude handles the rest and shows you a draft
before anything is sent.

The CLI underneath, if you want it directly:

```bash
python3 -m pmail parse --vn "Email Sara and Raj that the release slipped, cc finance."
python3 -m pmail draft new --vn "<transcript>" --subject "Release moved" --body-file body.txt
python3 -m pmail draft list
python3 -m pmail draft edit <id> --cc finance --subject "Release moved to Friday"
python3 -m pmail send <id> --confirm
python3 -m pmail history
```

`send` without `--confirm` is a dry run.

---

## What stops the wrong email going out

| Guard | What it does |
| --- | --- |
| Two-key send | Needs both `--confirm` **and** `PMAIL_ALLOW_SEND=1`. Either alone is a dry run. |
| Address book only | An address must be in `contacts.json` or spelled out in the note. Unknown names are refused, never guessed. |
| Mentioned-not-routed | Warns when the note names someone who is not a recipient. |
| Header injection | Refuses any newline in a subject or address, so a mis-transcribed note cannot add its own `Bcc`. |
| Domain allowlist | `PMAIL_ALLOWED_DOMAINS=acme.com` refuses everything outside those domains. |
| Recipient cap | `PMAIL_MAX_RECIPIENTS` (default 25) catches a mis-parsed group blast. |
| Re-send lock | A sent draft will not send again without `--resend`. |
| Audit log | Every send is appended to `history/sent.jsonl` and committed. |

And the one that matters most: Claude shows you the full draft and waits for
your yes, every time.

---

## Limits, honestly

- **Audio files are not transcribed here.** Voice notes recorded in the Claude
  app arrive as text and work fine. A raw `.m4a` attachment does not — there is
  no speech-to-text in this container.
- **Sending is not autonomous.** Each email needs your approval in the moment.
  That is deliberate: an email cannot be unsent.
- **Drafts are ephemeral.** They live in the container. Contacts and history are
  committed; drafts are not.
- **The API transport cannot attach files.** Zoho uploads attachments through a
  separate endpoint. Use SMTP when you need attachments.

## Tests

```bash
python3 -m unittest discover -s tests -t .
```
