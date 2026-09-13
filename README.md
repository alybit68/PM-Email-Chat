# PM-Email-Chat

Send a voice note, get an email — drafted for review, then sent from your Zoho
mailbox.

You dictate something like *"email Sara and the dev team that the release
slipped to Friday, cc finance"*. Claude resolves the names against your address
book, writes the actual email, shows you the full draft, and sends it only
after you say yes.

Python 3.9+, standard library only. Nothing to install.

---

## Where you run it decides how it connects

This matters more than anything else in the setup, so it comes first.

| | Claude Code **on the web** (cloud session) | **Your own machine** (terminal / Desktop app) |
| --- | --- | --- |
| SMTP (port 465) | **Blocked.** Cloud sessions route only HTTPS through an egress proxy; raw TCP has no route out, and no allowlist setting changes that. | Works. |
| Zoho REST API (HTTPS) | Works **after** you allowlist the Zoho hosts — see step 0. | Works. |
| Credential needed | OAuth Self Client (client id, secret, refresh token). | An app password is enough. |

So: **on the web, use `PMAIL_TRANSPORT=api`. Locally, SMTP with an app password
is simpler.** `python3 -m pmail doctor --live` tells you which situation you are
in and names the fix.

---

## Setup

> **Setting this up on the web?** Follow [`docs/SETUP.md`](docs/SETUP.md) —
> it is the same information as below, in click-by-click order.

### 0. (Cloud sessions only) Let the session reach Zoho

At [claude.ai/code](https://claude.ai/code), in the row above the message box,
select the cloud icon showing the environment name. Hover the environment,
select the settings (gear) icon, set **Network access** to **Custom**, and add
to **Allowed domains**:

```
mail.zoho.com
accounts.zoho.com
```

Use your region's hosts if you are not on the US data centre (`mail.zoho.eu`,
`mail.zoho.in`, …; Canada uses `mail.zohocloud.ca`). Tick **Also include
default list of common package managers** so git and pip keep working.

Then **start a new session** — a running session keeps the settings it started
with.

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

**On the web:** same dialog as step 0 — the **Environment variables** box.
One `KEY=value` per line, `.env` format, no quotes needed. These are copied
into each new session at startup, so they survive the container being wiped.
Edit them and start a new session for the change to take effect.

Note the values are visible to anyone who uses that environment.

**Locally:** copy `.env.example` to `.env` and fill it in. It is gitignored.

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
python3 -m pmail contacts add --key sara-remax --name "Sara Diaz" \
  --company "RE/MAX" --email sara.diaz@remax.example --groups listings
```

`--company` is what lets a voice note say **"Sara from RE/MAX"** and reach the
right person when you know two Saras. Spelling does not matter: `RE/MAX`,
`remax`, `Re-Max` and `sara at remax` all resolve to the same contact. A bare
company name addresses everyone there.

If you say just "Sara" and two Saras are on file, nothing is sent — you get
asked which one. An address is never guessed from a name or a company.

See `contacts.example.json` for the file format, including groups. **Commit
`contacts.json`** — the container is wiped between sessions.

---

## Arabic voice notes

Send the note in Arabic; the email goes out in formal English.

Claude translates meaning into English business register — Arabic directness
that would read as aggressive in English gets softened into ordinary courtesy,
while the substance is left alone. A deadline stays a deadline and a complaint
stays a complaint; only the tone changes. Numbers, dates, names and amounts
pass through exactly as spoken, and nothing is added that you did not say.
When something is softened, Claude says so, so you can ask for it firmer.

Two things to know:

- **Recipients are not guessed from Arabic.** Attached prepositions and dialect
  make that unreliable, and a wrong recipient cannot be recalled — so Claude
  reads the note and confirms who it is for rather than letting a parser guess.
- **Contacts are bilingual.** Store both spellings once and either language
  finds the person:

  ```bash
  python3 -m pmail contacts add --key sara-remax --name "Sara Diaz" \
    --email sara.diaz@remax.example \
    --company "RE/MAX" --company-aliases "ريماكس" --aliases "سارة"
  ```

  Then `سارة من ريماكس`, `سارة ريماكس` and `Sara from RE/MAX` all resolve to
  her. Arabic-Indic digits fold too, so `بت٦٨` matches `بت68`.

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

## Subject lines

Every subject is built to the house format:

```
[Bit68 - Oakwood] - Release moved to Friday
[Bit68 - Internal] - Offsite dates
```

You don't type the prefix. Say the project in the voice note and Claude passes
`--project "Oakwood"`; say it's internal and it passes `--internal` (the word
"internal", "in-house" or "the team" in a note is picked up automatically). A
draft whose subject doesn't match the format is refused at send time, so it
can't be forgotten in a rush.

Change the org name with `PMAIL_SUBJECT_ORG=Acme`, or turn the rule off
entirely with `PMAIL_SUBJECT_CONVENTION=0`.

This is not only a house style. The Zoho organisation enforces it as an
outbound email policy, so a subject outside the format is refused by the mail
server with `554 5.7.7 Policy Violation in Subject`. Enforcing it locally means
you find out while drafting rather than at send time.

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
| Subject format | A subject outside `[Bit68 - <project>] - <title>` is refused. |
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
  separate endpoint. Use SMTP when you need attachments — which, per the table
  at the top, means running pmail from your own machine.

## Tests

```bash
python3 -m unittest discover -s tests -t .
```
