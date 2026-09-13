# One-time setup (Claude Code on the web)

Follow this once. Afterwards you just send voice notes.

Why OAuth and not the app password: a cloud session routes only HTTPS through
an egress proxy, so a mail (SMTP) connection has no route out — the app
password has nothing to connect with. Zoho's HTTPS API does work, once the
environment is allowed to reach it. (If you ever run this on your own computer
instead, SMTP and an app password are the easier path — see the README.)

---

## Step 1 — Let the session reach Zoho

1. Go to [claude.ai/code](https://claude.ai/code).
2. In the row **above the message box**, click the cloud icon showing your
   environment's name (probably **Default**).
3. Hover that environment in the menu, click the **gear** icon on the right.
4. Set **Network access** to **Custom**.
5. In **Allowed domains**, add these two lines:

   ```
   accounts.zoho.com
   mail.zoho.com
   ```

   Not on the US data centre? Use your region's hostnames instead — `.eu`,
   `.in`, `.com.au`, `.jp`, `.sa`; Canada is `accounts.zohocloud.ca` and
   `mail.zohocloud.ca`. Your region is whichever domain you sign in to Zoho at.

6. Tick **Also include default list of common package managers**, so git and
   pip keep working.
7. Save.

## Step 2 — Create the Zoho Self Client

A "Self Client" is an API identity for your own account. It is not published
and nobody else can use it.

1. Go to [api-console.zoho.com](https://api-console.zoho.com) and sign in with
   the Zoho account you send mail from.
2. **Add Client** → choose **Self Client** → **Create**.
3. Open the **Client Secret** tab. You now have a **Client ID** and a
   **Client Secret**. Keep this tab open.

## Step 3 — Store the identity (not in chat)

Back in the environment dialog from step 1, in the **Environment variables**
box, add these lines. Paste the real values from the Client Secret tab —
put them here, not into the conversation.

```
PMAIL_TRANSPORT=api
ZOHO_EMAIL=you@yourdomain.com
ZOHO_FROM_NAME=Your Name
ZOHO_REGION=us
ZOHO_CLIENT_ID=<Client ID>
ZOHO_CLIENT_SECRET=<Client Secret>
PMAIL_ALLOW_SEND=1
```

Save, then **start a new session**. A running session keeps the settings it
started with, so the change only lands in a fresh one.

## Step 4 — Generate a code and hand it over

Authorization codes expire in minutes, so do this bit in one go.

1. In the API console, open your Self Client → **Generate Code** tab.
2. **Scope** — paste exactly:

   ```
   ZohoMail.messages.CREATE,ZohoMail.accounts.READ
   ```

3. **Time Duration** — pick the longest offered (default is 3 minutes).
4. **Scope Description** — anything, e.g. `PM-Email-Chat`.
5. **CREATE**, pick your account/portal if asked, and copy the code.
6. Paste the code straight into the new Claude session. It is single-use and
   expires in minutes, so it is not worth much on its own — unlike the client
   secret, which stays in the settings box.

Claude runs:

```bash
python3 -m pmail auth --code <the code>
```

and prints a `ZOHO_REFRESH_TOKEN=...` line.

## Step 5 — Store the refresh token

Add that `ZOHO_REFRESH_TOKEN=...` line (and `ZOHO_ACCOUNT_ID=...` if printed)
to the same Environment variables box, save, and start one more new session.

The refresh token does not expire. It will have appeared in the session
transcript — if you would rather it had not, revoke it in the API console
(**Self Client → Revoke**) and repeat steps 4–5 once more, after which the
live token exists only in your settings.

## Step 6 — Check it

```bash
python3 -m pmail doctor --live
```

Expect a reachable network path and `token valid, accountId=...`. Nothing is
sent by this check.

Then send yourself a real one as a test: *"Email me at
you@yourdomain.com saying this is a test."* Claude will show you the draft and
wait for your yes.

---

## If something goes wrong

| What you see | What it means |
| --- | --- |
| `Tunnel connection failed: 403` | Step 1 is missing or you are in a session that started before you saved it. Start a new session. |
| `invalid_code` | The code expired or was already used. Generate a fresh one and paste it straight away. |
| `invalid_client` | `ZOHO_REGION` does not match the data centre where you created the Self Client. |
| `smtp.zoho.com:465 timed out` | `PMAIL_TRANSPORT=api` is missing, so it is still trying SMTP. |
| `INVALID_OAUTHSCOPE` | The scope line in step 4 was wrong. Both scopes are needed, comma-separated, no spaces. |
| `554 5.7.7 Policy Violation in Subject` | Despite the wording this is almost never the subject. It means the From address is not validated for sending. Run `python3 -m pmail doctor --live`, which checks this explicitly, then verify the domain (MX, SPF, DKIM) at mailadmin.zoho.com. |
