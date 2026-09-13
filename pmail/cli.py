"""Command line entry point: python3 -m pmail <command>

Design rule: sending is the only destructive act here, and it takes two
independent unlocks — the PMAIL_ALLOW_SEND environment switch and an explicit
--confirm on the command. Everything else is a dry run by default.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__, audit, net, transcript
from .config import Config
from .contacts import AddressBook, Contact
from .drafts import Draft
from .errors import PmailError
from .message import Message, address_of
from .senders import send as dispatch
from .subject import format_subject, project_of


def _read_text(inline: str | None, path: str | None) -> str:
    """Accept text inline, from a file, or from stdin via '-'."""
    if inline:
        return inline
    if path == "-":
        return sys.stdin.read()
    if path:
        return Path(path).read_text(encoding="utf-8")
    return ""


def _csv(value: str | None) -> list[str]:
    return [v.strip() for v in (value or "").split(",") if v.strip()]


def _format(contacts: list[Contact]) -> list[str]:
    """Addresses as they go into headers — display name only, no company."""
    return [c.display for c in contacts]


def _labels(contacts: list[Contact]) -> list[str]:
    """Company-qualified, for showing a human which person was picked."""
    return [c.label for c in contacts]


# ---------------------------------------------------------------------------
# doctor
# ---------------------------------------------------------------------------


def cmd_doctor(args: argparse.Namespace) -> int:
    config = Config.load()
    book = AddressBook.load()

    print(f"pmail {__version__}")
    print(f"  transport       {config.transport}")
    print(f"  region          {config.region} ({config.account_type})")
    if config.transport == "smtp":
        print(f"  smtp            {config.smtp_host}:{config.smtp_port}")
    else:
        print(f"  api             {config.api_base}")
    print(f"  from            {config.email or '(unset)'}")
    print(f"  contacts        {len(book.contacts)} people, {len(book.groups)} groups")
    print(f"  allowed domains {', '.join(config.allowed_domains) or '(all)'}")
    print(f"  max recipients  {config.max_recipients}")

    missing = config.missing_for_transport()
    if missing:
        print(f"\n  ✗ not ready — missing: {', '.join(missing)}")
        print("    Set these in your environment (or .env). See .env.example.")
    else:
        print("\n  ✓ credentials present")

    lock = "UNLOCKED" if config.allow_send else "LOCKED (dry-run only)"
    print(f"  send switch     PMAIL_ALLOW_SEND={lock}")

    if args.live:
        print("\n  checking the network path...")
        reachable = net.probe(config)
        print(f"  {'✓' if reachable.ok else '✗'} {reachable.summary}")
        if reachable.hint:
            print(f"      {reachable.hint}")
        if not reachable.ok:
            return 1

        if missing:
            print("\n  skipping credential check — credentials missing")
            return 1
        print("\n  contacting Zoho...")
        try:
            if config.transport == "smtp":
                from .senders.smtp import check_connection
            else:
                from .senders.zoho_api import check_connection
            print(f"  ✓ {check_connection(config)}")
        except PmailError as exc:
            print(f"  ✗ {exc}")
            return 1

    return 0 if not missing else 1


# ---------------------------------------------------------------------------
# auth
# ---------------------------------------------------------------------------


def cmd_auth(args: argparse.Namespace) -> int:
    """One-time: turn a Self Client authorization code into a refresh token."""
    from .senders.zoho_api import account_id, exchange_code

    config = Config.load()

    reachable = net.probe_api(config)
    if not reachable.ok:
        print(f"✗ {reachable.summary}", file=sys.stderr)
        if reachable.hint:
            print(f"  {reachable.hint}", file=sys.stderr)
        return 1

    payload = exchange_code(config, args.code)
    refresh = payload["refresh_token"]

    account = ""
    try:
        account = account_id(config, payload["access_token"])
    except PmailError:
        pass  # Not fatal: the send path looks it up on demand.

    print("Refresh token obtained. Add these to your environment variables")
    print("(claude.ai/code -> cloud icon -> gear -> Environment variables),")
    print("then start a NEW session:\n")
    print("PMAIL_TRANSPORT=api")
    print(f"ZOHO_REFRESH_TOKEN={refresh}")
    if account:
        print(f"ZOHO_ACCOUNT_ID={account}")
    print("\nThe refresh token does not expire. It is now in this "
          "conversation, so if you would rather it were not, revoke it in the "
          "API console after pasting and run this again with a fresh code.")
    return 0


# ---------------------------------------------------------------------------
# contacts
# ---------------------------------------------------------------------------


def cmd_contacts(args: argparse.Namespace) -> int:
    book = AddressBook.load()

    if args.contacts_command == "list":
        if not book.contacts:
            print("No contacts yet. Add one:")
            print('  python3 -m pmail contacts add --key sara --name "Sara Diaz" '
                  '--email sara@acme.com --groups dev-team')
            return 0
        width = max(len(c.key) for c in book.contacts)
        for contact in sorted(book.contacts, key=lambda c: c.key):
            groups = f"  [{', '.join(contact.groups)}]" if contact.groups else ""
            print(f"  {contact.key:<{width}}  {contact.label}{groups}")
        if book.groups:
            print("\nGroups:")
            for name, members in sorted(book.groups.items()):
                print(f"  {name}: {', '.join(members)}")
        return 0

    if args.contacts_command == "add":
        existing = book.by_key(args.key)
        if existing and not args.force:
            print(f"Contact {args.key!r} already exists ({existing.display}). "
                  "Pass --force to overwrite.", file=sys.stderr)
            return 1
        book.contacts = [c for c in book.contacts if c.key.lower() != args.key.lower()]
        contact = Contact(
            key=args.key,
            name=args.name or "",
            email=args.email,
            company=args.company or "",
            aliases=tuple(_csv(args.aliases)),
            groups=tuple(_csv(args.groups)),
            notes=args.notes or "",
        )
        book.contacts.append(contact)
        for group in contact.groups:
            members = book.groups.setdefault(group, [])
            if contact.key not in members:
                members.append(contact.key)
        path = book.save()
        print(f"Saved {contact.display} to {path}")
        print("Commit contacts.json so it survives the next session.")
        return 0

    if args.contacts_command == "remove":
        if not book.by_key(args.key):
            print(f"No contact {args.key!r}.", file=sys.stderr)
            return 1
        book.contacts = [c for c in book.contacts if c.key.lower() != args.key.lower()]
        for members in book.groups.values():
            if args.key in members:
                members.remove(args.key)
        book.save()
        print(f"Removed {args.key}.")
        return 0

    if args.contacts_command == "resolve":
        contacts, problems = book.resolve_all(args.tokens)
        for line in _labels(contacts):
            print(f"  ✓ {line}")
        for problem in problems:
            print(f"  ✗ {problem}", file=sys.stderr)
        return 1 if problems else 0

    return 1


# ---------------------------------------------------------------------------
# parse
# ---------------------------------------------------------------------------


def cmd_parse(args: argparse.Namespace) -> int:
    text = _read_text(args.vn, args.vn_file)
    if not text.strip():
        print("Nothing to parse. Pass --vn \"...\" or --vn-file path (or -).",
              file=sys.stderr)
        return 1

    parsed = transcript.parse(text)
    book = AddressBook.load()

    print("Routing read from the voice note:")
    for label, tokens in (("to", parsed.to), ("cc", parsed.cc), ("bcc", parsed.bcc)):
        if not tokens:
            continue
        contacts, problems = book.resolve_all(tokens)
        print(f"  {label}: {', '.join(tokens)}")
        for line in _labels(contacts):
            print(f"       ✓ {line}")
        for problem in problems:
            print(f"       ✗ {problem}")

    if parsed.is_empty():
        print("  (no recipients detected — pass --to explicitly)")
    if parsed.subject_hint:
        print(f"  subject hint: {parsed.subject_hint}")
    if parsed.urgent:
        print("  marked urgent")
    if parsed.body_hint:
        print(f"  body hint: {parsed.body_hint[:200]}")
    return 0


# ---------------------------------------------------------------------------
# draft
# ---------------------------------------------------------------------------


def _build_draft(args: argparse.Namespace) -> tuple[Draft, list[str]]:
    config = Config.load()
    book = AddressBook.load()
    text = _read_text(args.vn, args.vn_file)
    parsed = transcript.parse(text)

    warnings: list[str] = []

    def resolve(explicit: str | None, fallback: list[str], label: str) -> list[str]:
        tokens = _csv(explicit) if explicit else fallback
        contacts, problems = book.resolve_all(tokens)
        warnings.extend(f"{label}: {p}" for p in problems)
        return _format(contacts)

    to = resolve(args.to, parsed.to, "to")
    cc = resolve(args.cc, parsed.cc, "cc")
    bcc = resolve(args.bcc, parsed.bcc, "bcc")

    body = _read_text(args.body, args.body_file) or parsed.body_hint
    subject = format_subject(
        args.subject or parsed.subject_hint,
        project=args.project,
        internal=args.internal or (parsed.internal and not args.project),
    )

    message = Message(
        subject=subject,
        body=body,
        to=to,
        cc=cc,
        bcc=bcc,
        reply_to=args.reply_to or "",
        attachments=list(args.attach or []),
        urgent=args.urgent or parsed.urgent,
    )

    # Cross-check: did the speaker name someone the mail is not going to?
    routed = {address_of(r).lower() for r in message.all_recipients}
    for contact in book.mentioned_in(text):
        if contact.email.lower() not in routed:
            warnings.append(
                f"{contact.label} is named in the voice note but is not a recipient."
            )

    draft = Draft(transcript=text, note=args.note or "", message=message)
    warnings.extend(message.validate(config))
    return draft, warnings


def cmd_draft(args: argparse.Namespace) -> int:
    config = Config.load()

    if args.draft_command == "new":
        draft, warnings = _build_draft(args)
        draft.save()
        print(draft.message.preview(config))
        print("-" * 60)
        print(f"Draft {draft.id} saved to {draft.path}")
        if warnings:
            print("\nNeeds attention before sending:")
            for warning in warnings:
                print(f"  ! {warning}")
        print(f"\nSend it with:  python3 -m pmail send {draft.id} --confirm")
        return 0

    if args.draft_command == "list":
        drafts = Draft.all()
        if not drafts:
            print("No drafts.")
            return 0
        for draft in drafts:
            print(draft.summary())
        return 0

    if args.draft_command == "show":
        draft = Draft.load(args.id)
        print(draft.message.preview(config))
        print("-" * 60)
        print(f"id {draft.id}  status {draft.status}  created {draft.created_at}")
        if draft.sent:
            print(f"sent {draft.sent.get('at')} via {draft.sent.get('transport')}")
        if draft.transcript:
            print(f"\nOriginal voice note:\n{draft.transcript}")
        return 0

    if args.draft_command == "edit":
        draft = Draft.load(args.id)
        if draft.status == "sent":
            print(f"Draft {draft.id} was already sent; edit is refused.", file=sys.stderr)
            return 1
        book = AddressBook.load()
        message = draft.message

        for label, value in (("to", args.to), ("cc", args.cc), ("bcc", args.bcc)):
            if value is None:
                continue
            contacts, problems = book.resolve_all(_csv(value))
            for problem in problems:
                print(f"  ✗ {problem}", file=sys.stderr)
            if problems:
                return 1
            setattr(message, label, _format(contacts))

        if args.subject is not None or args.project or args.internal:
            # Changing only the title must not silently drop the project the
            # draft already carried, so read it from the draft, not the title.
            carried = project_of(message.subject)
            message.subject = format_subject(
                args.subject if args.subject is not None else message.subject,
                project=args.project or (None if args.internal else carried),
                internal=args.internal,
            )
        if body := _read_text(args.body, args.body_file):
            message.body = body
        if args.reply_to is not None:
            message.reply_to = args.reply_to
        if args.attach:
            message.attachments = list(args.attach)
        if args.urgent:
            message.urgent = True

        draft.save()
        print(draft.message.preview(config))
        print("-" * 60)
        if problems := message.validate(config):
            print("Needs attention before sending:")
            for problem in problems:
                print(f"  ! {problem}")
        print(f"Updated {draft.id}.")
        return 0

    if args.draft_command == "cancel":
        draft = Draft.load(args.id)
        draft.status = "cancelled"
        draft.save()
        print(f"Cancelled {draft.id}.")
        return 0

    return 1


# ---------------------------------------------------------------------------
# send
# ---------------------------------------------------------------------------


def cmd_send(args: argparse.Namespace) -> int:
    config = Config.load()
    draft = Draft.load(args.id)

    if draft.status == "sent" and not args.resend:
        print(f"Draft {draft.id} was already sent at {draft.sent.get('at')}. "
              "Pass --resend to send it again.", file=sys.stderr)
        return 1
    if draft.status == "cancelled":
        print(f"Draft {draft.id} is cancelled.", file=sys.stderr)
        return 1

    print(draft.message.preview(config))
    print("-" * 60)

    if problems := draft.message.validate(config):
        print("Refusing to send:", file=sys.stderr)
        for problem in problems:
            print(f"  ! {problem}", file=sys.stderr)
        return 1

    config.require_ready()

    # Two independent locks so neither a stray --confirm nor a set-and-forgotten
    # environment variable is enough on its own.
    if not args.confirm:
        print("DRY RUN — nothing sent. Add --confirm to send.")
        return 0
    if not config.allow_send:
        print("DRY RUN — nothing sent. PMAIL_ALLOW_SEND is not set, which is the "
              "master switch.\nSet PMAIL_ALLOW_SEND=1 in the environment to enable "
              "real sends.", file=sys.stderr)
        return 1

    detail = dispatch(draft.message, config)
    draft.mark_sent(config.transport, detail)
    log = audit.record(draft.id, draft.message, config.transport, detail, draft.transcript)

    print(f"Sent. {detail}")
    print(f"Recorded in {log}")
    return 0


# ---------------------------------------------------------------------------
# history
# ---------------------------------------------------------------------------


def cmd_history(args: argparse.Namespace) -> int:
    entries = audit.tail(args.limit)
    if not entries:
        print("Nothing sent yet.")
        return 0
    for entry in entries:
        recipients = ", ".join(entry.get("to", []))
        print(f"{entry['at']}  {entry.get('subject', '')[:44]:<44}  → {recipients}")
    return 0


# ---------------------------------------------------------------------------
# wiring
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pmail",
        description="Turn voice-note transcripts into reviewed Zoho Mail sends.",
    )
    parser.add_argument("--version", action="version", version=f"pmail {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    doctor = sub.add_parser("doctor", help="check configuration and credentials")
    doctor.add_argument("--live", action="store_true",
                        help="also authenticate against Zoho (sends nothing)")
    doctor.set_defaults(func=cmd_doctor)

    auth = sub.add_parser(
        "auth", help="exchange a Zoho Self Client code for a refresh token"
    )
    auth.add_argument("--code", required=True,
                      help="the authorization code from the API console")
    auth.set_defaults(func=cmd_auth)

    contacts = sub.add_parser("contacts", help="manage the address book")
    csub = contacts.add_subparsers(dest="contacts_command", required=True)
    csub.add_parser("list", help="show every contact and group")
    add = csub.add_parser("add", help="add or update a contact")
    add.add_argument("--key", required=True, help="short handle, e.g. sara")
    add.add_argument("--email", required=True)
    add.add_argument("--name", help="display name")
    add.add_argument("--company", help='employer, so "Sara from RE/MAX" resolves')
    add.add_argument("--aliases", help="comma-separated extra names heard in voice notes")
    add.add_argument("--groups", help="comma-separated groups, e.g. dev-team,leads")
    add.add_argument("--notes")
    add.add_argument("--force", action="store_true", help="overwrite an existing key")
    remove = csub.add_parser("remove", help="delete a contact")
    remove.add_argument("--key", required=True)
    resolve = csub.add_parser("resolve", help="test how names resolve to addresses")
    resolve.add_argument("tokens", nargs="+")
    contacts.set_defaults(func=cmd_contacts)

    parse_cmd = sub.add_parser("parse", help="show the routing read from a transcript")
    parse_cmd.add_argument("--vn", help="transcript text inline")
    parse_cmd.add_argument("--vn-file", help="transcript file, or - for stdin")
    parse_cmd.set_defaults(func=cmd_parse)

    draft = sub.add_parser("draft", help="create and review drafts")
    dsub = draft.add_subparsers(dest="draft_command", required=True)

    new = dsub.add_parser("new", help="build a draft from a transcript")
    new.add_argument("--vn", help="transcript text inline")
    new.add_argument("--vn-file", help="transcript file, or - for stdin")
    new.add_argument("--to", help="override recipients (comma-separated keys/groups)")
    new.add_argument("--cc")
    new.add_argument("--bcc")
    new.add_argument("--subject")
    new.add_argument("--project",
        help="project or client name for the subject prefix")
    new.add_argument("--internal", action="store_true",
        help="use 'Internal' as the subject's project slot")
    new.add_argument("--body", help="body text inline")
    new.add_argument("--body-file", help="body file, or - for stdin")
    new.add_argument("--reply-to")
    new.add_argument("--attach", action="append", help="file to attach (repeatable)")
    new.add_argument("--urgent", action="store_true")
    new.add_argument("--note", help="internal note, never sent")

    dsub.add_parser("list", help="list drafts")
    show = dsub.add_parser("show", help="show one draft")
    show.add_argument("id")

    edit = dsub.add_parser("edit", help="change a draft before sending")
    edit.add_argument("id")
    edit.add_argument("--to")
    edit.add_argument("--cc")
    edit.add_argument("--bcc")
    edit.add_argument("--subject")
    edit.add_argument("--project",
        help="project or client name for the subject prefix")
    edit.add_argument("--internal", action="store_true",
        help="use 'Internal' as the subject's project slot")
    edit.add_argument("--body")
    edit.add_argument("--body-file")
    edit.add_argument("--reply-to")
    edit.add_argument("--attach", action="append")
    edit.add_argument("--urgent", action="store_true")

    cancel = dsub.add_parser("cancel", help="mark a draft as cancelled")
    cancel.add_argument("id")
    draft.set_defaults(func=cmd_draft)

    send_cmd = sub.add_parser("send", help="send a draft (dry run without --confirm)")
    send_cmd.add_argument("id")
    send_cmd.add_argument("--confirm", action="store_true",
                          help="actually send; without this it is a dry run")
    send_cmd.add_argument("--resend", action="store_true",
                          help="allow sending a draft that was already sent")
    send_cmd.set_defaults(func=cmd_send)

    history = sub.add_parser("history", help="show what has been sent")
    history.add_argument("-n", "--limit", type=int, default=20)
    history.set_defaults(func=cmd_history)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except PmailError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nAborted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
