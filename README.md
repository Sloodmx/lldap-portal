# LLDAP Portal

A small self-hosted Flask application that handles two things for [LLDAP](https://github.com/lldap/lldap):

- **Invitations**: an admin creates an invite link, and the invited person creates their own LLDAP account after confirming a 6-digit code sent by email. The account is then added automatically to the LLDAP groups matching the **roles** selected on the invite.
- **Password reset**: users request a reset link by email, valid for 24 hours and single-use.

Roles are fully configurable: none are created by default. Add them from the Configuration page with two fields (a display name and an LLDAP group).

## Quick start

### 1. Prepare the `.env` file

Next to your `docker-compose.yml`, create a `.env` file:

```env
TZ=
LLDAP_VOLUME=
```

`LLDAP_VOLUME` is the host folder under which the portal stores its data (`${LLDAP_VOLUME}/ldap-invite/data`).

### 2. Docker Compose

```yaml
services:
  lldap-portal:
    build:
      context: ./lldap-portal
      dockerfile: Dockerfile
      args:
        APP_UID: 1000
        APP_GID: 1000
    container_name: lldap-portal
    restart: unless-stopped
    environment:
      DATA_DIR: /app/data
      TZ: ${TZ}
    ports:
      - "5000:5000"
    volumes:
      - :/app/data
    healthcheck:
      test: ["CMD", "python", "-c",
             "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5000/healthz', timeout=2)"]
      interval: 30s
      timeout: 3s
      retries: 3
      start_period: 10s
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"
```

```bash
docker compose up -d --build
```

### 3. Permissions on the data folder

The container starts as root, sets the data folder to the owner `APP_UID:APP_GID` (1000:1000 by default), then drops privileges before starting Gunicorn.

If you run the container without root (for example with `user: "1000:1000"`, or on Kubernetes), fix the ownership yourself on the host first:


Use `id -u` and `id -g` to find the right values for your system, and match them with `APP_UID` and `APP_GID`.

### 4. First visit

Open `http://<host>:<port>/admin`:

1. Create the administrator account (username and password, 12 characters minimum). There is no admin password to put in the compose file.
2. Open the **Configuration** tab and fill in SMTP and LDAP/LLDAP settings, then save.
3. Send a test email to check the SMTP setup.
4. Create an invite and share the generated link.

## Where the configuration is stored

Everything entered in the **Configuration** tab, including the admin password, is saved in one file:

```
settings.json     permissions 0600, back this up
```

It contains the application name, the public URL, SMTP settings (`smtp_pass`), LLDAP settings (`lldap_admin_password`), the invite roles and `admin_password_hash`.

Other files in the same folder:

| File | Contents |
| --- | --- |
| `settings.json` | All configuration and the admin password hash |
| `invites.json` | Active invites (hashes of the codes, uses, expiry) |
| `audit.log` | Audit log (logins, invites, errors), no secrets |
| `.secret_key` | Session signing key (0600, regenerated if missing) |

Notes on secrets:

- **Admin password**: never stored in clear text. `settings.json` only keeps a `scrypt:...` hash.
- **SMTP and LLDAP passwords**: stored in clear text in `settings.json`, which is why the file is `0600`. Protect any backup of it as you would a secret.
- **Invite codes**: only their SHA-256 fingerprint is saved. If a link is lost, create a new invite.
- `settings.json` only appears after the first save in the Configuration tab. Until then the defaults are used, and the interface says so.
- `.secret_key` starts with a dot, so use `ls -A` to see it.

Always back up the data folder. Without it you lose the configuration, pending invites and the session key.

## Configuration

Everything is set in the web interface (`/admin` → **Configuration**):

| Section | Settings |
| --- | --- |
| General | Service name, public URL (optional), trusted proxies (CIDR) |
| Email (SMTP) | Server, port, security (STARTTLS / SSL / none), user, password, sender address, timeout |
| LDAP directory | LDAP URL, base DN, GraphQL URL, technical account and password, timeout |
| Password reset | Service account, allowed groups, cooldown between requests, login page link |
| Invitation roles | Roles offered when creating an invite (display name and LLDAP group) |
| Administrator access | Username, new password |
| Test | Send a test email |

Secrets (SMTP password, LLDAP technical account password) are never shown again in the browser or written to the audit log. Leaving a secret field empty keeps the existing value.

Environment variables are optional. They only pre-fill the configuration on the very first start (`DATA_DIR`, `SECRET_KEY`, `APP_NAME`, `APP_URL`, `TRUSTED_PROXIES`, `SMTP_*`, `LLDAP_*`, `LDAP_TIMEOUT`, `LLDAP_GROUP_ID_*`, `RESET_*`, `LOGIN_URL`, `ADMIN_USERNAME`, `ADMIN_PASSWORD_HASH`). Once you save in the interface, `settings.json` takes priority.

### Two URLs for LLDAP

LLDAP exposes two interfaces, and the portal uses both:

| Field | Purpose | Example |
| --- | --- | --- |
| **LDAP URL** (`ldap://`) | Checks that a username or email is free, and sets the password of the new account (RFC 3062 extended operation) | `ldap://lldap:3890` |
| **GraphQL URL** (HTTP) | Creates the account, adds it to the role groups, and deletes it if a step fails | `http://lldap:17170` |

LDAP cannot create users, so account creation goes through LLDAP's GraphQL API on the web port (17170). The portal logs in with the technical account to get a token.

The GraphQL URL must start with `http://` or `https://` and point to the web interface (port 17170), not `ldap://`. If only one of the two URLs is filled in, the configuration is considered incomplete and sign-ups will fail.

### Roles

In **Configuration → Invitation roles**, each role has two fields:

| Field | Purpose | Example |
| --- | --- | --- |
| **Display name** | What the visitor and the admin see | `Media` |
| **LLDAP group** | Group the new user is added to | `jellyfin` (or the numeric ID, e.g. `4`) |

- **Add**: click **+ Add a role**, fill both fields, then save. Empty rows are ignored.
- **Rename**: change the display name and save. The internal key is kept, so existing invites keep working. Update the LLDAP group field too if the group was renamed.
- **Delete**: clear both fields and save. Clearing only one of the two fields is refused, to prevent accidental deletions.
- Up to **20 roles**. Display names must be unique.

If you were using the older `LLDAP_GROUP_ID_JELLYFIN` / `LLDAP_GROUP_ID_SILO` variables, those two roles are migrated automatically on first start. Otherwise, no role exists until you add one.

If a role is deleted after an invite was created, it is skipped at sign-up and the event is logged as `role_absent`.

On the **Invites** page, each role is a checkbox. The display name in the applications is always the same as the username.

### Local access without a domain

Leave **Public URL** empty. The app accepts requests from any host (`http://localhost:5000`, `http://192.168.x.x:5000`, a domain name, or a reverse proxy), and invite links use the address the browser actually used.

- Only POST requests whose `Origin` points to a different host are rejected (CSRF protection). A missing `Origin` header is accepted.
- Session and sign-up cookies are marked `Secure` only when the public URL starts with `https://`, so they keep working over plain HTTP on a local network.
- Behind a reverse proxy, `X-Forwarded-Proto` and `X-Forwarded-Host` are only trusted for the addresses listed in **Trusted proxies**.

## Password reset

Users can request a reset link at `https://<your-domain>/password-reset` (or `http://<host>:5000/password-reset` on the local network). The link is valid for 24 hours and works once.

### Setup

1. In LLDAP, create a dedicated service account (for example `ldap-reset-pass`) and give it **only** the `lldap_password_manager` role.
2. In **Configuration → Password reset**:
   - *Service account*: the username (not the DN);
   - *Service account password*: saved in `settings.json`;
   - *Allowed groups* (optional): comma-separated LLDAP group names. If set, only members of those groups can reset. Empty means all accounts;
   - *Cooldown*: 600 seconds by default;
   - *Login page* (optional): URL for the "Back to sign-in" link.
3. Set the **Public URL** in the General section. Password reset requires it. Without it, the link in the email would be built from the `Host` header, which anyone can forge, so the request is refused.

The Password reset status on the Configuration page should show *configured*.

### Behaviour

- The response never reveals whether an account exists. Processing happens in the background, and the user always sees the same confirmation page.
- A given identifier can only trigger one request per cooldown period.
- The link contains only a random token. The audit log never records the token or the password, only a short reference.
- The password is set with the LDAP extended operation (RFC 3062) using the service account. Sign-ups keep using the technical LLDAP account.

## Invite names and history cleanup

- **Invite name** (optional, when creating an invite): not shown to the visitor. It appears in the invite list and the audit log, which helps you remember why a link was created.
- **Purge inactive invites**: removes revoked, expired or fully used invites from the list. Active invites are kept. The action is logged.

## Usernames and uppercase letters

Usernames, emails and display names are sent to LLDAP in lowercase, since LLDAP is case-insensitive. Passwords keep their case.

## Troubleshooting

### "Internal Server Error" when validating the username and password

The data folder mounted into the container is owned by another user, so `settings.json` cannot be written. Fix the ownership on the host as described in step 3 and restart the container. The app shows the exact command to run instead of a bare 500 page.

```bash
curl -i http://localhost:5000/healthz      # 503 if the data folder is not writable
docker compose logs lldap-portal            # look for "Permission denied"
```

### Only `invites.json` is visible in the data folder

This is normal after the first start. `settings.json` is only created on the first save in the Configuration tab. `.secret_key` is hidden, so use `ls -A`. The **Configuration → Data files** section shows which files are present or missing.

### The test email fails (SMTP)

The **Configuration → Test email** section displays the real response from the SMTP server, the settings actually applied (never passwords), and a suggested fix. Common causes:

- **`535` / authentication refused**: Gmail, Outlook and Yahoo require an **app password** (16 characters, no spaces) and two-factor authentication.
- **Spaces or line breaks pasted with the password**: the field is cleaned on save, but check it if the error persists.
- **Wrong security for the port**: STARTTLS goes with 587, SSL with 465.
- **Timeout**: the SMTP host may not resolve from the container, or a firewall blocks the port.
- **Local relay without AUTH**: leave the user field empty.

Details are also logged, without secrets:

```bash
docker compose logs lldap-portal | grep mail_failed
```

### Other checks

```bash
docker compose config -q                    # validate the compose file
curl -i http://localhost:5000/healthz      # health check
```

## Security

- Rate limiting on every sensitive route (Flask-Limiter)
- Optional Cloudflare Turnstile on public forms
- Origin checking on POST requests
- Session cookies: `HttpOnly`, `SameSite=Strict`, `Secure` over HTTPS, absolute lifetime of one hour
- Security headers (CSP, HSTS over HTTPS, `X-Frame-Options`, and others)
- Files created with `0600` permissions, secrets never redisplayed
- Identical response whether or not an account exists during password reset
- The container drops root privileges at startup

Password policy: at least 10 characters, with an uppercase letter, a digit and a special character.

## Stack

Python 3.12, Flask, Gunicorn (1 worker, 8 threads, because the rate limiter is in memory), ldap3, Flask-Limiter, Docker.

## License

MIT