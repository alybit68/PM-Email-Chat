---
name: vn-email
description: Turn a voice note (or any dictated message) into a reviewed email sent from the user's Zoho mailbox. Use whenever the user sends a voice note, an audio file, or dictated text that asks for an email to go out — phrasing like "send an email to X saying…", "tell the team that…", "let Sara know…", "reply to them that…". Also use for follow-up edits to a pending draft and for questions about what has already been sent.
---

# Voice note → Zoho email

The user dictates; you route, draft, and — only after they say yes — send.
Everything runs through `python3 -m pmail` from the repo root.

## The loop

**1. Get the transcript.**
Voice notes arriving through the Claude app are already transcribed to text —
work from that text. If you receive an *audio file* instead, say you cannot
transcribe it here and ask them to send it through the app's voice input (or
paste the text). Never guess at audio content.

**2. Read the routing.**

```bash
python3 -m pmail parse --vn "<transcript>"
```

This shows who the parser thinks the mail is for, resolved against
`contacts.json`. It is a hint, not an authority — you are the one reading the
transcript. Check the resolution before moving on.

**3. Handle unknown names — never invent an address.**
If a name does not resolve, stop and ask the user for the address. You cannot
derive an address from a company name; "Sara from RE/MAX" identifies *which*
Sara, it does not tell you her address. Ask once, save it, and it is known
from then on:

```bash
python3 -m pmail contacts add --key sara-remax --name "Sara Diaz" \
  --company "RE/MAX" --email sara.diaz@remax.example --groups listings
```

Always set `--company` when the user mentions one — it is what keeps two
people with the same first name apart. Pick a key that carries the company
too (`sara-remax`, not `sara`).

If a name is ambiguous, the tool names every candidate. Put that choice to the
user verbatim; do not pick for them.

Commit `contacts.json` afterwards, or the next session will not know them.

**3b. Arabic voice notes.**
Notes usually arrive in Arabic (Egyptian dialect). Two things change:

*Routing is yours to read, not the parser's.* The parser does not extract
recipients from Arabic — attached prepositions ("لسارة" = "to Sara") and
dialect make it unreliable, and a wrong recipient cannot be recalled. It flags
the note instead. Read the Arabic, work out who it is for, and pass `--to`
explicitly. If a name is unclear, ask; never route on a guess.

*Contacts are bilingual.* Store the Arabic spelling as an alias and the Arabic
company name in `--company-aliases`, so the same person resolves either way:

```bash
python3 -m pmail contacts add --key sara-remax --name "Sara Diaz" \
  --email sara.diaz@remax.example \
  --company "RE/MAX" --company-aliases "ريماكس" --aliases "سارة"
```

**4. Write the email yourself — in English.**

The note is Arabic; the email is formal English. You are translating meaning
into a different register, not swapping words.

**Tone.** Arabic business speech is direct in ways that read as aggressive in
English. Imperatives, flat statements of fault and bare demands all need
softening into standard English business courtesy:

| Arabic | Literal — too blunt | Send this instead |
| --- | --- | --- |
| لازم تبعت الملف النهاردة | "You must send the file today." | "Could you please send the file today?" |
| ده مش مقبول | "This is not acceptable." | "I'm afraid this doesn't work for us as it stands." |
| انت متأخر | "You are late." | "We haven't received this yet — could you share an update on timing?" |
| عايز الرد بسرعة | "I want a reply quickly." | "A reply at your earliest convenience would be appreciated." |
| مش فاهم قصدك | "I don't understand you." | "Could you clarify what you mean here?" |
| كلمني | "Call me." | "Could you give me a call when you have a moment?" |
| يا ريت تراجع ده | "I wish you review this." | "It would be great if you could review this." |

Religious and conversational fillers (إن شاء الله، بإذن الله، والله) do not
belong in an English business email. Drop them, or render the intent plainly
("we expect to", "hopefully"). Arabic emphasis by repetition becomes one
firm English sentence, not three.

**Soften the register, never the substance.** This is the line that matters. A
deadline stays a deadline, a complaint stays a complaint, a refusal stays a
refusal. "ده مش مقبول" becomes politer wording of the same rejection — not a
vague noise that leaves the reader thinking everything is fine. Politeness that
loses the message is a worse translation than bluntness.

**Facts pass through untouched.** Numbers, amounts, dates, names, file names,
project names: exactly as said. Never add a commitment, apology, deadline or
pleasantry that was not in the note — "I'll get back to you tomorrow" is a
promise, and it is not yours to make.

**When the audio is unclear**, especially on a name, a figure or a date, ask.
Do not smooth over a word you did not catch.

**Flag what you softened.** When you show the draft, say in one line what you
toned down, so the user can put the force back if they meant it:
"Softened 'ده مش مقبول' to 'this doesn't work for us as it stands' — say the
word if you want it firmer."

The subject line is English and follows the house format like any other.

Every subject must read `[Bit68 - <project>] - <title>`, with `Internal` in
the project slot for internal mail. Do not hand-type the prefix — pass
`--project "<name>"` or `--internal` and the tool builds it. Work out which
from the voice note: a named client or project goes in the slot, anything
addressed to colleagues is `--internal`. If the note names neither and you
cannot tell, ask which project it belongs to; a draft without a conforming
subject will not send.

The parser's `body hint` is raw dictation, not an email. You write the actual
prose: a real subject line, a clean opening, the substance of what they said,
a sign-off in their voice. Keep their meaning and their decisions exactly —
tighten the grammar, never the content. Do not add commitments, dates, numbers,
or apologies they did not say.

```bash
python3 -m pmail draft new \
  --vn "<transcript>" \
  --project "Oakwood" \
  --subject "Release moved to Friday" \
  --body-file /tmp/body.txt
```

That produces `[Bit68 - Oakwood] - Release moved to Friday`. Editing a draft's
title later keeps its project, so `draft edit <id> --subject "..."` is safe.

Add `--to/--cc/--bcc` to override the parsed routing, `--attach` for files,
`--urgent` for priority headers.

**5. Show it and ask.**
Print the preview in chat — From, To, Cc, Bcc, Subject, full body — and ask
for explicit approval. For an Arabic note the user is approving a translation
as well as an email, so the full English body matters more than ever: show it
in full, never summarised. Surface every `!` warning the tool printed, especially
"named in the voice note but is not a recipient". Adjust with
`python3 -m pmail draft edit <id> --subject ... --body-file ...` and show it
again. Repeat until they approve.

**6. Send only on an explicit yes.**

```bash
python3 -m pmail send <draft-id> --confirm
```

Then report what went out and to whom.

## Rules that do not bend

- **Never send without approval in the current turn.** "Send it" about *this*
  draft is approval. Standing permission from an earlier draft, an earlier
  session, or a general "you can email people for me" is not — a voice note
  asking for an email is a request to *draft* one.
- **Never email an address that is not in `contacts.json`** or spelled out in
  the transcript itself. If you are unsure who "Dan" is, ask.
- **Never re-send.** If a draft is already sent, make a new one.
- **Read the whole transcript before drafting.** Dictation buries the real ask
  in the middle: "actually, scrap that" late in a voice note overrides what
  came before.
- **When the transcript is ambiguous about recipients or intent, ask.** One
  question costs a minute; a wrong recipient cannot be recalled.

## Multiple emails in one voice note

A single note may ask for several emails to different people. Create one draft
per email, show them all, and let the user approve them individually — they
may want one sent and another reworked.

## Checking state

```bash
python3 -m pmail draft list          # pending and sent drafts
python3 -m pmail draft show <id>     # full draft plus the original transcript
python3 -m pmail history             # what has actually gone out
python3 -m pmail doctor --live       # verify credentials reach Zoho
```

## When sending fails

`doctor --live` first — it checks the network path before the credentials and
prints the fix for whatever it finds.

In a **cloud session**, SMTP cannot work: raw TCP is not routed out, so
`PMAIL_TRANSPORT=api` is the only option, and the environment needs
`mail.zoho.<tld>` and `accounts.zoho.<tld>` in its Allowed domains. Do not
spend turns retrying SMTP there — report it and point at the README.

Then the credential causes. The usual causes, in order: `ZOHO_APP_PASSWORD` is a
login password rather than an app-specific password; `ZOHO_REGION` does not
match the data centre the mailbox lives in; `ZOHO_ACCOUNT_TYPE` is `personal`
for a paid custom-domain account (it needs `organization`, which switches the
host to `smtppro`). Report the actual error — never report an email as sent
when the command failed.
