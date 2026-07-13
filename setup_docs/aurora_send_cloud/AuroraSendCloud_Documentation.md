# AuroraSendCloud — Complete Reference & Implementation Guide

### What it is, what it provides, pricing, and exactly how this repo uses it

> This document consolidates the raw notes in [`AuroraSendCloud_Guide.md`](AuroraSendCloud_Guide.md)
> with a direct read of this project's actual implementation
> (`src/email_platform/sendcloud_provider.py`, `src/webhook_factory/sendcloud_webhook.py`,
> `src/config.py`, `src/services/conversation_service.py`). Anything marked
> **⚠️ Unconfirmed** comes only from inference, not from a verified AuroraSendCloud
> API response or official schema — treat it as "best current guess" until
> validated against a real payload or docs.aurorasendcloud.com.

---

## Table of Contents

1. [What Is AuroraSendCloud](#1-what-is-aurorasendcloud)
2. [Regions & Base URLs](#2-regions--base-urls)
3. [Activating a Region (Dashboard)](#3-activating-a-region-dashboard)
4. [Pricing](#4-pricing)
5. [Domain Authentication (SPF / DKIM / MX / DMARC)](#5-domain-authentication-spf--dkim--mx--dmarc)
6. [This Project's jobsetu.online DNS Setup](#6-this-projects-jobsetuonline-dns-setup)
   (where to retrieve the records on the AuroraSendCloud dashboard, then the
   step-by-step Hostinger hPanel walkthrough for root domain + subdomain)
7. [Outbound Sending — Basic Send API](#7-outbound-sending--basic-send-api)
8. [Inbound Route — Receiving Replies](#8-inbound-route--receiving-replies)
   (step-by-step webhook route configuration, prerequisites, best practices, troubleshooting)
9. [End-to-End Code Flow in This Repo](#9-end-to-end-code-flow-in-this-repo)
10. [Configuration Reference](#10-configuration-reference)
11. [Known Gaps, Risks & Bugs](#11-known-gaps-risks--bugs)
12. [Testing & Local Development](#12-testing--local-development)
13. [References](#13-references)

---

## 1. What Is AuroraSendCloud

AuroraSendCloud is the email-sending platform this project integrates with
under the provider key `sendcloud` (`src/email_platform/sendcloud_provider.py`,
`src/webhook_factory/sendcloud_webhook.py`). It offers:

- **Transactional/API email sending** — a "Basic Send" HTTP API
  (`/api/mail/send`) that accepts `multipart/form-data`, used for this app's
  outbound RFQ emails. There is no first-party Python SDK, so this repo talks
  to it directly with `requests` (mirroring the approach already used for the
  Mailgun provider).
- **Domain authentication** — SPF, DKIM (with two modes — "Automated Security"
  and "Classic"), MX, and DMARC, the same authentication stack used by
  SendGrid/Mailgun/etc.
- **Inbound Route** — forwards incoming *replies* to a previously-sent message
  either to an email address or to a webhook URL. This is the mechanism this
  app depends on to receive supplier replies.
- **Multi-region infrastructure** — three independent regions (Singapore, US,
  Hong Kong/CN), each with its own base URL, dashboard, quota, and API
  credentials.
- **Prepaid email packages** — one-time credit purchases (not a monthly
  subscription) valid for 12 months from purchase.

Official docs: `docs.aurorasendcloud.com`. Marketing site: `aurorasendcloud.com`.

---

## 2. Regions & Base URLs

| Region | Base URL | Best used for |
|---|---|---|
| **Singapore** (default) | `https://api.aurorasendcloud.com/` | Indian systems sending to Indian or global users — the closest APAC region to India-hosted infrastructure (AWS Mumbai, GCP Delhi, etc.) |
| **CN / Hong Kong** | `https://api-hk.aurorasendcloud.com/` | Chinese systems sending to Chinese mailboxes (QQ, NetEase), or any system specifically targeting mainland China deliverability |
| **US (Silicon Valley)** | `https://api-us.aurorasendcloud.com/` | Systems physically hosted in North America, or businesses primarily serving Western/US audiences |

**Rule of thumb:** pick the region closest to where your *servers* run, not
where your recipients are.

**⚠️ Critical constraint — credentials are region-locked.** An `apiUser`/`apiKey`
pair generated in one region's dashboard view will return an auth error against
any other region's base URL. Every newly-registered account defaults to the
Singapore region.

This project defaults to Singapore (`src/config.py:135-137`):

```python
self.sendcloud_api_base = os.getenv(
    "SENDCLOUD_API_BASE", "https://api.aurorasendcloud.com"
).rstrip("/")
```

If you ever change `SENDCLOUD_API_BASE` in `.env`, you must also swap in a
new `SENDCLOUD_API_USER`/`SENDCLOUD_API_KEY` pair generated under that
region's dashboard view — the existing pair will not work.

---

## 3. Activating a Region (Dashboard)

Only Singapore is active by default. To send from US or Hong Kong you must
activate the region first:

1. Log in to the AuroraSendCloud dashboard → **Account/Profile** → **Info -
   Regions**.
2. Under **"Add Region"**, select **US (Silicon Valley)** or **CN (Hong
   Kong)**, click **Add**, and confirm. (Activation is free; usage still
   draws from that region's own quota/billing plan.)
3. A region switcher appears in the dashboard's top bar — use it to flip the
   console view between Singapore / US / Hong Kong.
4. **While viewing the new region**, go to **API Key Management** and
   generate a **new** API user + API key scoped to that region. Keys are not
   portable across regions.
5. Update your application's base URL *and* credentials together — never
   just one of the two.

---

## 4. Pricing

Prepaid packages, **effective February 1, 2026**. All packages **expire
after 1 year** from purchase — this is a one-time credit purchase, not a
recurring monthly subscription.

| Package (emails) | Price (1 year) |
|---|---|
| 10,000 | US $29.90 |
| 30,000 | US $85.00 |
| 50,000 | US $130.00 |
| 100,000 | US $250.00 |
| 150,000 | US $360.00 |
| 300,000 | US $670.00 |
| 500,000 | US $1,050.00 |
| 500,000+ | Contact Us |

Note: pricing/quota is almost certainly tracked **per activated region** (see
§3) — sending from Singapore and Hong Kong likely draws from two separate
pools. **⚠️ Unconfirmed** — verify against your dashboard's billing page
before assuming a single combined quota across regions.

---

## 5. Domain Authentication (SPF / DKIM / MX / DMARC)

Your **sending domain** is what appears in the SMTP `MAIL FROM` command and
is the single biggest factor in inbox placement vs. spam-foldering.

| Record | Required? | Purpose |
|---|---|---|
| **SPF** (TXT) | ✅ Mandatory | Whitelists which IPs may send as your domain — blocks spoofing |
| **DKIM** (CNAME or TXT) | ✅ Mandatory | Cryptographically signs outgoing mail so receivers can verify it wasn't tampered with |
| **MX** | ✅ Mandatory | Where mail *to* your domain gets delivered — required even for a send-only domain, and is what makes **Inbound Route** possible |
| **DMARC** (TXT) | Optional but strongly recommended | Policy for what to do when SPF/DKIM fail, plus aggregate reporting |

**Important:** every new account gets an auto-provisioned test domain.
**Never send production email from the test domain** — always authenticate
your own business domain first.

### DKIM: Automated Security vs. Classic

| Mode | Behavior |
|---|---|
| **Automated Security DKIM** | Adds **two CNAME records** to your DNS instead of a static TXT key. The CNAMEs delegate DKIM public-key resolution to AuroraSendCloud's infrastructure, which rotates the underlying key automatically (default: every 120 days) with zero action from you. |
| **Classic DKIM** | Generates a single static TXT record (1024-bit or 2048-bit). No rotation — stays fixed until you regenerate it manually. |

This project's DNS setup (§6) uses **Automated Security DKIM** — that's why
it configures two CNAMEs (`e1._domainkey`, `e2._domainkey`) rather than a
DKIM TXT record.

### Domain status meanings

| Status | Meaning |
|---|---|
| ⚪ **Unverified** | SPF/DKIM/MX missing or wrong — domain cannot send |
| 🔵 **Usable** | SPF/DKIM/MX all pass — can send, but DMARC (optional) may still be unconfigured |
| 🟢 **Verified** | Everything, including DMARC, passes — optimal deliverability |

### Best practice: separate domains by email type

AuroraSendCloud (like most ESPs) recommends splitting transactional mail
(e.g. `notifications.yourbusiness.com`) from marketing mail
(`marketing.yourbusiness.com`) so a marketing sending-reputation problem
never impacts critical transactional delivery. This project currently sends
everything (RFQs) from a single subdomain, `mail.jobsetu.online` — fine for
a POC, worth revisiting if a marketing use case is added later.

---

## 6. This Project's jobsetu.online DNS Setup

The concrete setup performed for this repo's domain, `jobsetu.online`,
hosted on **Hostinger (hPanel)**.

### 6a. Where to find/retrieve these DNS records on the AuroraSendCloud dashboard

Per AuroraSendCloud's official "Domain" documentation, this is a two-part
process: first **retrieve** the record values from the AuroraSendCloud
dashboard, then **paste** them into your DNS provider (Hostinger, for this
project — see §6b and §6c).

**Step 1 — Access Domain Management**

1. Log in to the AuroraSendCloud dashboard.
2. Navigate to **Setting → Domain** in the left sidebar.
3. Click **Add Domain** if this is your first business domain (or the
   first time you're adding this specific domain/subdomain).
4. Enter the domain name — e.g. `jobsetu.online` for the root domain
   (§6b), or `mail.jobsetu.online` for the subdomain (§6c). Each one is
   added as its **own** domain entry.

> If your DNS is hosted on DNSPod, AuroraSendCloud has a dedicated
> walkthrough at
> `docs.aurorasendcloud.com/update/docs/how-to-configure-your-domain-on-dnspod`.
> Hostinger isn't in their provider-specific list, so use the generic steps
> below — the record *values* AuroraSendCloud gives you are identical no
> matter which DNS provider you paste them into.

**Step 2 — Retrieve the DNS records**

1. Select the domain from the domain list (after adding it in Step 1).
2. Its detail page shows a table of records to add — usually labeled
   something like **"Record To Configure"** — with columns for record
   **Type**, **Host/Name**, and **Value**.
3. Copy each value **exactly** as shown. Some values (particularly DMARC)
   are visually **truncated in the UI** — click the eye icon or the copy
   button next to the field to get the complete, untruncated string before
   pasting it anywhere.
4. Note down every record type you're given — for this project's
   Automated Security DKIM setup that's **SPF, MX, two DKIM CNAMEs
   (`e1`/`e2`), and DMARC**.

**Step 3 — Configure your DNS provider**

This is the Hostinger portion — see §6b (root domain) and §6c (subdomain)
below for the exact click-path. In general:

- **SPF** → add as a TXT record
- **MX** → add as an MX record with the correct priority
- **DKIM** → add as a CNAME (Automated Security mode, used here — see §5)
  or TXT (Classic mode) record, usually under a selector subdomain
- **DMARC** → add as a TXT record at `_dmarc.yourdomain.com`

**Step 4 — Wait for propagation**

DNS changes typically take **10–30 minutes** to propagate; some providers
or record types can take up to 24 hours.

**Step 5 — Verify configuration**

Return to the domain's settings page on the AuroraSendCloud dashboard and
click **Verify** (labeled **Configuration Check** elsewhere in the
dashboard) to re-check your live DNS against what was requested:

| Status | Meaning |
|---|---|
| ⚪ **Unverified** | One or more required records (SPF, DKIM, MX) are missing or wrong — domain cannot send |
| 🔵 **Usable** | SPF, DKIM, MX all resolve correctly — domain can send; DMARC (optional) may still be pending |
| 🟢 **Verified** | Every configured record, including DMARC, resolves correctly — optimal deliverability |

### 6b. Root domain (`jobsetu.online`) — add the retrieved records in Hostinger

**Step-by-step in Hostinger hPanel:**

1. Log in to **Hostinger** → **Domains** → select `jobsetu.online`.
2. Open **DNS / Nameservers** → **DNS Zone Editor** (Hostinger sometimes
   labels this just **"DNS Zone"** under the domain's management page).
3. Add each record below using **"Add New Record"**. Leave TTL at the
   default (usually `14400`) unless you want faster propagation for testing
   (you can temporarily set it to `300`).
4. Click **Save** after each record.

| Record | Type | Host / Name | Value / Points to |
|---|---|---|---|
| SPF | TXT | `@` | `v=spf1 include:spf.sendcloud.org -all` |
| DKIM 1 | CNAME | `e1._domainkey` | `e1._domainkey.rhfwgnrq-sg.dkim.aurorasendcloud.org` |
| DKIM 2 | CNAME | `e2._domainkey` | `e2._domainkey.rhfwgnrq-sg.dkim.aurorasendcloud.org` |
| DMARC | TXT | `_dmarc` | `v=DMARC1;p=reject;ruf=mailto:dmarc@jobsetu.online;...` (copy the **full** value from the dashboard — it's truncated in the UI, click the eye icon or copy button to get the complete string) |
| MX | MX | `@` | `mx2.sendcloud.org` (priority `10` unless the dashboard says otherwise) |

5. For the **Host/Name** field, enter just the prefix — e.g. `e1._domainkey`,
   `_dmarc`, or `@` — **not** the full FQDN. Hostinger auto-appends
   `.jobsetu.online` itself; typing the full name produces a doubled suffix
   like `e1._domainkey.jobsetu.online.jobsetu.online`.

Hostinger-specific gotchas:
- Enter only the prefix (e.g. `e1._domainkey`), not the full FQDN — Hostinger
  auto-appends the domain.
- If a TXT record already exists at `@`, **merge** the SPF value into it
  instead of adding a second TXT record (two SPF TXT records on one host
  breaks validation).
- If an MX record already exists at `@`, replace it or reconcile priorities
  — two MX records pointing at different mail servers causes unpredictable
  delivery.

Verify propagation:

```bash
dig TXT jobsetu.online +short
dig CNAME e1._domainkey.jobsetu.online +short
dig CNAME e2._domainkey.jobsetu.online +short
dig TXT _dmarc.jobsetu.online +short
dig MX jobsetu.online +short
```

Then run **Configuration Check** in the dashboard; status flips
`Unverified` → `Verified` once all four record types resolve correctly.

### 6c. Subdomain (`mail.jobsetu.online`) — used for actual sending

The app sends from `*@mail.jobsetu.online`
(`INBOUND_DOMAIN=mail.jobsetu.online` in `.env`), not the bare root domain,
so the subdomain needs its **own** SPF/DKIM entry. This spans **two
platforms** — don't confuse them:

- **AuroraSendCloud dashboard** (the "Domain Authentication" screen) — this
  is where you tell the platform you want to authenticate a subdomain, and
  it *generates* the DNS records you need.
- **Hostinger** — this is where you *paste* those generated records, the
  same way as Step 6b above.

Since there is typically no "Advanced Settings" or custom-subdomain toggle,
the usual approach is to **add the subdomain as its own domain entry**:

**Step-by-step:**

1. On the **AuroraSendCloud dashboard**, go to wherever `jobsetu.online` was
   originally added — likely a **"Domains"** list or an **"Add Domain" /
   "+"** button on the Domain Authentication page.
2. Add a **new domain entry** and type `mail.jobsetu.online` directly
   (instead of just `jobsetu.online`).
3. The platform treats this as a separate domain to authenticate and
   generates its own set of DNS records scoped to it, typically:

   | Record | Host | Type |
   |---|---|---|
   | SPF | `mail` | TXT |
   | DKIM | `e1._domainkey.mail` | CNAME |
   | DKIM | `e2._domainkey.mail` | CNAME |

   (exact selector names may differ for this entry — use whatever the
   dashboard shows you, not the root domain's `e1`/`e2` selectors from
   Step 6b)
4. Switch to **Hostinger** → DNS Zone Editor → add these new records the
   same way as Step 6b (Host field = prefix only, e.g. `e1._domainkey.mail`
   — Hostinger appends `jobsetu.online` automatically).
5. Back on the **AuroraSendCloud dashboard**, run **Configuration Check**
   again for this subdomain entry — wait for it to show `Verified`.

> If you don't see a way to add `mail.jobsetu.online` as its own entry,
> share a screenshot of the "Add Domain" / domain-list screen — the exact
> option may be named differently on your account.

**Why this matters even if the dashboard has no explicit subdomain flow:**
DMARC checks the *organizational* domain, so root-level DKIM (`d=jobsetu.online`)
still passes DKIM alignment for mail sent from `mail.jobsetu.online`. SPF,
however, is checked against the **exact** sending domain — so without the
subdomain's own SPF TXT record, SPF specifically will fail for
`mail.jobsetu.online` even though DKIM passes. Add the subdomain SPF record
regardless of whether subdomain DKIM CNAMEs exist.

### 6d. Verifying end-to-end

```bash
export SENDCLOUD_API_KEY="your_api_key_here"
python send_email.py   # or: uv run python main.py, then use the UI
```

Send to a Gmail address → open it → **⋮ → Show original** → confirm
`SPF: PASS`, `DKIM: PASS`, `DMARC: PASS`. If any fail:

- **SPF FAIL** → subdomain SPF TXT record missing/not propagated.
- **DKIM FAIL** → check `DKIM-Signature: d=` in the raw headers and confirm
  the matching CNAME resolves (`dig CNAME e1._domainkey.mail.jobsetu.online +short`).
- **DMARC FAIL** → almost always cascades from an SPF/DKIM failure — fix
  those first.

---

## 7. Outbound Sending — Basic Send API

### Endpoint & auth model

```
POST {SENDCLOUD_API_BASE}/api/mail/send
Content-Type: multipart/form-data
```

Unlike most providers, AuroraSendCloud does **not** accept credentials via
HTTP Basic Auth or a bearer header — `apiUser` and `apiKey` are sent as
regular fields **in the request body**, alongside the message fields.

### Implementation — `src/email_platform/sendcloud_provider.py`

`SendCloudEmailProvider` extends the shared `EmailMaster` base
(`src/email_platform/email_master.py`) that every provider inherits, which
supplies:

- `generate_conversation_id()` — 8-hex-char conversation id.
- `build_dynamic_email(user_name, conv_id)` — builds
  `{CamelCaseName}-{conv_id}@{INBOUND_DOMAIN}`, e.g.
  `JamesWhitfield-3fa9c1b2@mail.jobsetu.online`.
- `parse_dynamic_email(address)` — reverses that to recover `conv_id` from
  an inbound `To` address (also matches a legacy `prefix_conv{id}` format).
- `build_rfq_subject` / `build_rfq_html` — renders the actual RFQ template
  (product/quantity/target price table + inline base64 banner image).

`SendCloudEmailProvider` only adds the two things a provider must supply
itself:

```python
# src/email_platform/sendcloud_provider.py
data = {
    "apiUser": self.api_user,
    "apiKey": self.api_key,
    "from": from_email,       # the dynamic conversation address
    "fromName": from_name,    # COMPANY_NAME
    "to": to_email,
    "subject": subject,
    "html": html_body,
}
files = [("attachments", (filename, content, content_type)) for att in attachments]
response = requests.post(self.send_url, data=data, files=files or None, ...)
```

### Response handling

A response is only treated as success when **all** of these hold:
- HTTP status is 2xx,
- the body parses as JSON,
- `body["result"]` is truthy (SendCloud can return HTTP 200 with
  `result: false` on an application-level failure — e.g. bad sender).

On success, the provider message id is read from
`body["info"]["emailIdList"][0]`.

```json
// Example successful response shape
{
  "statusCode": 200,
  "result": true,
  "info": { "emailIdList": ["<some-id>"] }
}
```

Any network error, non-2xx status, unparseable body, or `result: false`
raises `EmailSendError`, which `src/route.py`'s `/send` handler catches and
turns into a user-facing error banner instead of a 500 page.

### How the app uses this (`ConversationService.send_rfq`)

Both `From` **and** `Reply-To` are set to the same dynamic per-conversation
address (`src/services/conversation_service.py:242-251`) — this is the
mechanism that routes a supplier's reply back to the right conversation
without any external lookup table.

---

## 8. Inbound Route — Receiving Replies

### How AuroraSendCloud's Inbound Route actually works

- It is **not** a general inbound-mail catcher. Per the official docs:
  > "Emails sent directly to the configured address will not be forwarded
  > by default. Only be processed when the recipient replies to the email
  > you sent."

  In other words, Inbound Route is reply-tracking, not a generic mailbox —
  which is exactly the semantics this app needs, since the dynamic address
  is only ever used as a `Reply-To` on a message *this app already sent*.
  A cold email sent directly to a dynamic address (never sent from this app
  first) would **not** be forwarded.

- **Two delivery methods**, chosen per route:
  - **Email Forwarding** — relays the reply to a verified inbox. Requires a
    one-time "Get Verification Code" email confirmation.
  - **Webhook URL** — POSTs the parsed reply as JSON/form data to an
    HTTP(S) endpoint. **This is the method this app requires**, pointed at
    `POST /email_poc/webhooks/inbound`.

- **Address pattern matching** — a route is scoped to a domain plus a
  prefix pattern: a literal prefix (`support` → `support@yourdomain.com`)
  or a regex (`.*` → catch-all, `reply-.*` → `reply-123@...`). Because this
  app's addresses are fully dynamic
  (`{CamelCaseName}-{conv_id}@mail.jobsetu.online` — a different prefix on
  every conversation), **the route must be configured with a catch-all
  regex pattern (`.*`) on `mail.jobsetu.online`**, not a fixed prefix.

- **Activation delay** — a newly created/edited route takes effect within
  **10 minutes** (DNS + rule propagation).

- **⚠️ Attachments are not included.** Per AuroraSendCloud's own
  documentation, Inbound Route "focuses purely on conversation text and
  metadata rather than extracting and caching raw binary file attachments."
  Only the outbound Basic Send API accepts `multipart/form-data`
  attachments — inbound replies do not carry them through this feature at
  all. If attachment capture on supplier replies is a hard requirement, the
  documented workaround is pointing MX directly at your own mail server (or
  an intermediary capturing the raw multipart stream) instead of relying on
  Inbound Route's text-only relay.

### Prerequisites (per AuroraSendCloud docs)

Before creating a route:

- **MX Record Configuration** — must already be live (§6a: `mx2.sendcloud.org`,
  priority `10`) so inbound mail actually reaches AuroraSendCloud's servers
  in the first place.
- **Domain Access** — administrative access to add/verify DNS records.
- **Email Verification** — only required for the **Email Forwarding**
  method (confirming you own the destination inbox). **Not required** for
  the **Webhook URL** method this app uses.

### Step-by-step: configure the Webhook Inbound Route (the method this app needs)

This app requires **Method 2 — Push to Webhook URL**, so `/email_poc/webhooks/inbound`
receives every supplier reply as an HTTP POST:

1. **Choose Domain** — in the AuroraSendCloud dashboard's Inbound Route
   setup screen, select `mail.jobsetu.online` (the domain whose MX record
   was configured in §6a).
2. **Inbound Route** — enter the prefix/pattern together with the domain to
   form the matched address. Because this app's addresses are fully
   dynamic (`{CamelCaseName}-{conv_id}@mail.jobsetu.online` — a different
   prefix per conversation), you must use the **catch-all regex `.*`**, not
   a fixed prefix:

   | Pattern | Matches | Works for this app? |
   |---|---|---|
   | `support` | `support@mail.jobsetu.online` | ❌ fixed prefix — conversation addresses vary |
   | `reply-.*` | `reply-123@mail.jobsetu.online` | ❌ prefixes here aren't `reply-`-prefixed |
   | `.*` | any address on the domain | ✅ **required** — matches every generated `{Name}-{conv_id}` address |

3. **Configure URL** — enter the complete webhook URL, including scheme:
   `https://<your-domain-or-ngrok>/email_poc/webhooks/inbound`. Must start with
   `http://` or `https://`.
4. **Verify Endpoint** — confirm the URL is publicly reachable and can
   accept a POST before saving. This app's `POST /email_poc/webhooks/inbound`
   handler already exists for this (`src/route.py`); it also implements a
   `GET /email_poc/webhooks/inbound` probe endpoint for providers (like Elastic
   Email) that validate a URL with a GET first.
5. **Test Connection** — use the dashboard's test/send feature, or trigger
   a real reply, to confirm AuroraSendCloud can deliver a payload to your
   endpoint and it responds with a 2xx.

**Timing:** a newly created or edited route takes effect within **10
minutes** (DNS + rule propagation) — don't assume it's broken if the first
test reply sent immediately after saving doesn't arrive.

> **Method 1 (Email Forwarding)** follows the same first two steps (Choose
> Domain, Inbound Route prefix) but then asks for a destination email
> address, a "Get Verification Code" confirmation step, and selecting the
> **API_USER** that handles the forwarding. This app does not use this
> method — it's documented here only for completeness in case the webhook
> path needs a fallback.

### Best practices (per AuroraSendCloud docs)

1. **Test your setup** — send real test replies to verify routing end to end.
2. **Monitor performance** — make sure your webhook endpoint responds quickly.
3. **Secure your URLs** — use HTTPS for the webhook URL whenever possible.
4. **Plan for volume** — ensure your endpoint can handle expected reply traffic.

### Troubleshooting (per AuroraSendCloud docs)

| Symptom | What to check |
|---|---|
| Route not working at all | Is the MX record from §6a correctly configured? Have 10 minutes passed since creating/editing the route? |
| Webhook never fires / no incoming requests | Is the URL publicly accessible and does it return a proper status code? Check your server (or ngrok) logs for incoming POSTs |
| Replies missing | Check spam/junk folders on the forwarding side; confirm the address pattern (`.*`) actually matches the incoming `To` address |

### This project's inbound parser — status: best-effort stub

`src/webhook_factory/sendcloud_webhook.py` (`SendCloudWebhookParser`) exists
and is wired into `WebhookParserFactory`, but its field-name mapping was
**never validated against a real AuroraSendCloud inbound payload** — the
docstring is explicit about this:

> "SendCloud's inbound-mail webhook payload format has not been officially
> documented in this repo yet... This parser follows the same field-naming
> convention as SendGrid's Inbound Parse webhook... as a best-effort
> default."

Concretely, it currently assumes (for both `multipart/form-data` and JSON):

| Normalized field | Guessed multipart key | Guessed JSON key(s) |
|---|---|---|
| sender | `from` | `from` / `sender` |
| recipient | `to` | `to` / `recipient` |
| subject | `subject` | `subject` |
| plain text | `text` | `text` / `body_plain` |
| html | `html` | `html` / `body_html` |
| spam score | `spam_score` | `spam_score` |
| DKIM result | `dkim` | `dkim` |
| SPF result | `SPF` | `SPF` / `spf` |
| attachments | `attachment{N}` + `attachment-info` JSON blob (SendGrid convention) | base64 `content`/`data` per item |

Given §8's confirmation that Inbound Route doesn't relay attachments at
all, the attachment-extraction code paths above (`_extract_attachments`,
`_attachments_from_json`) will most likely never receive data — they're
speculative scaffolding, not confirmed-working code.

Also note: `WebhookParserMaster.verify_signature()` defaults to `True`
("trusted") for every provider except Mailgun, which overrides it with real
HMAC verification. **SendCloud inbound requests are not currently signature-
verified at all** — confirm whether AuroraSendCloud signs webhook payloads
before relying on this in anything beyond a POC.

**Bottom line:** outbound sending via SendCloud is production-real; inbound
reply parsing for SendCloud is not verified and should be treated as
"probably needs rework" until tested against one real reply.

---

## 9. End-to-End Code Flow in This Repo

### Sending an RFQ

```
Browser → POST /send  (src/route.py)
   → ConversationService.create_conversation
        → generates conv_id, builds dynamic address
          {CamelCaseName}-{conv_id}@mail.jobsetu.online
        → persists conversation in data/db.json
   → ConversationService.send_rfq
        → builds subject + HTML body (EmailMaster helpers)
        → SendCloudEmailProvider.send_email
             → POST {SENDCLOUD_API_BASE}/api/mail/send
                 (multipart/form-data: apiUser, apiKey, from, fromName,
                  to, subject, html, attachments[])
             → AuroraSendCloud delivers to supplier inbox
        → sent record appended to the conversation in data/db.json
   ← redirect to /tracking/{user_id}/{conv_id}
```

### Receiving a reply

```
Supplier hits "Reply" in their mail client
   → goes to {CamelCaseName}-{conv_id}@mail.jobsetu.online
   → MX (mx2.sendcloud.org) routes it to AuroraSendCloud
   → AuroraSendCloud Inbound Route (webhook mode, catch-all pattern)
        POSTs to /email_poc/webhooks/inbound
   → route.py: POST /email_poc/webhooks/inbound (src/route.py)
   → ConversationService.handle_inbound
        → WebhookParserFactory picks SendCloudWebhookParser
        → parser.parse(request) → InboundEmail (best-effort field mapping)
        → signature check (always "trusted" for sendcloud today)
        → spam_score > 5.0 → discarded
        → EmailMaster.parse_dynamic_email(to_email) → recovers conv_id
        → match against data/db.json conversations
        → persist attachments (if any arrive) + the reply record
        → _classify_reply() keyword-buckets the reply:
             QUOTE_RECEIVED / DECLINED / CLARIFICATION_NEEDED / MANUAL_REVIEW
   ← JSON status response (matched / unmatched / skipped / rejected / error)
```

Provider selection for *both* directions is one env var —
`EMAIL_PROVIDER=sendcloud` picks `SendCloudEmailProvider` **and**
`SendCloudWebhookParser` together (`src/email_platform/factory.py`,
`src/webhook_factory/factory.py`) — swapping providers never requires a
code change.

---

## 10. Configuration Reference

| Variable | Required | Default | Notes |
|---|---|---|---|
| `EMAIL_PROVIDER` | ✅ | `sendgrid` | Set to `sendcloud` to activate this provider for both send + inbound |
| `SENDCLOUD_API_USER` | ✅ (when active) | — | API user from the AuroraSendCloud console, region-specific |
| `SENDCLOUD_API_KEY` | ✅ (when active) | — | API key from the console, region-specific — regenerate per region |
| `SENDCLOUD_API_BASE` | ❌ | `https://api.aurorasendcloud.com` (Singapore) | `https://api-us.aurorasendcloud.com` (US) or `https://api-hk.aurorasendcloud.com` (HK) |
| `INBOUND_DOMAIN` | ✅ | — | Must match the domain the Inbound Route catch-all pattern is scoped to, e.g. `mail.jobsetu.online` |
| `FROM_EMAIL` | ✅ | — | Not actually used by the SendCloud provider today — it sends `from=reply_to` (the dynamic address), not `FROM_EMAIL` (see §11) |
| `COMPANY_NAME` | ❌ | `Your Company` | Used as `fromName` |

All of these are read once into a process-wide `Settings` singleton in
`src/config.py`; `SendCloudEmailProvider.__init__` fails fast with a clear
`ProviderConfigError` at startup if `SENDCLOUD_API_USER`/`SENDCLOUD_API_KEY`
are missing.

---

## 11. Known Gaps, Risks & Bugs

1. **🐞 Bug — outbound HTML body is hardcoded, ignoring the real RFQ
   content.** In `src/email_platform/sendcloud_provider.py`, `send_email`
   does this unconditionally before building the request:

   ```python
   html_body = "<h1>Hello World!</h1><p>Your first email via AuroraSendCloud API</p>"
   ```

   This overwrites the `html_body` parameter that was passed in (the real
   product/quantity/price RFQ table rendered by `EmailMaster.build_rfq_html`).
   **Every RFQ currently sent through SendCloud ships this placeholder
   instead of the actual quote content.** This line should simply be
   deleted so the real `html_body` argument flows through — it looks like
   leftover debug/test code from initial API exploration (see `test.py`,
   which has the same string).

2. **Inbound payload shape is unverified.** `SendCloudWebhookParser` guesses
   SendGrid's field-naming convention; it has not been checked against a
   real AuroraSendCloud inbound POST. Field names may not match at all.

3. **No inbound signature verification.** Unlike Mailgun's HMAC check,
   SendCloud inbound requests are accepted as "trusted" unconditionally.
   Confirm whether AuroraSendCloud signs Inbound Route webhook payloads
   before treating this as production-safe.

4. **Attachments on replies are likely unsupported**, per AuroraSendCloud's
   own Inbound Route documentation (text/metadata only — see §8). The
   attachment-decoding code in `sendcloud_webhook.py` may be dead code in
   practice.

5. **Region/credential coupling.** Changing `SENDCLOUD_API_BASE` without
   regenerating a matching `SENDCLOUD_API_USER`/`SENDCLOUD_API_KEY` pair
   under that region's dashboard view will produce authentication failures,
   not a helpful error.

6. **`FROM_EMAIL` is unused by this provider.** `ConversationService.send_rfq`
   passes `from_email=reply_to` (the dynamic conversation address) to every
   provider, including SendCloud — the configured `FROM_EMAIL` setting has
   no effect on the SendCloud path today. This matches SendGrid's intended
   dynamic-from design but is worth knowing if `FROM_EMAIL` was expected to
   be the visible sender.

7. **⚠️ Credential hygiene — `test.py`.** The untracked `test.py` script in
   the repo root has a real-looking `apiUser`/`apiKey` pair hardcoded in
   plaintext. Keep it out of version control (`git status` currently shows
   it as untracked/new, not yet committed) and rotate the key if it is ever
   pushed or shared.

---

## 12. Testing & Local Development

### Manual send test (ad-hoc script pattern used in `test.py`)

```python
import requests

url = "https://api.aurorasendcloud.com/api/mail/send"  # match your region
data = {
    "apiUser": "<from .env: SENDCLOUD_API_USER>",
    "apiKey": "<from .env: SENDCLOUD_API_KEY>",
    "from": "JamesWhitfield-3fa9c1b2@mail.jobsetu.online",
    "fromName": "Testing User",
    "to": "you@example.com",
    "subject": "Welcome to AuroraSendCloud",
    "html": "<h1>Hello World!</h1><p>Test email</p>",
}
response = requests.post(url, data=data, headers={"accept": "application/json"})
print(response.json())
```

Load real credentials from `.env` rather than hardcoding them — see the
security note in §11.

### Running the app end-to-end

```bash
uv sync
cp .env.example .env
# set EMAIL_PROVIDER=sendcloud and the SENDCLOUD_* variables
uv run python main.py
```

### Exposing localhost for the Inbound Route webhook

```bash
ngrok http 7000
# Configure the AuroraSendCloud Inbound Route (Webhook URL method) to:
#   https://<subdomain>.ngrok-free.app/email_poc/webhooks/inbound
# Route pattern: catch-all (.*) on mail.jobsetu.online
```

### Simulating an inbound reply without a real email

Field names are unconfirmed (see §8) — this mirrors the SendGrid-shaped
guess currently coded into `sendcloud_webhook.py`:

```bash
curl -X POST http://localhost:7000/email_poc/webhooks/inbound \
  -F "from=buyer@acme.com" \
  -F "to=JamesWhitfield-3fa9c1b2@mail.jobsetu.online" \
  -F "subject=RE: RFQ" \
  -F "text=Our price is \$11.50 per unit. MOQ 200 units." \
  -F "spam_score=0.1"
```

Replace the field names once a real AuroraSendCloud inbound payload has
been captured and confirmed.

---

## 13. References

- `https://docs.aurorasendcloud.com` — API/account/domain/webhooks reference
- `https://docs.aurorasendcloud.com/docs/route` — Inbound Route documentation
- `https://docs.aurorasendcloud.com/docs/webhooks` — Webhook payload structure
- `https://docs.aurorasendcloud.com/docs/account` — Region activation
- `https://www.aurorasendcloud.com` — Marketing site
- [`AuroraSendCloud_Guide.md`](AuroraSendCloud_Guide.md) — raw source notes this document was built from
- [`sendgrid_dynamic_domain_auth.md`](sendgrid_dynamic_domain_auth.md) — this repo's fully-verified SendGrid setup guide, useful as a working reference for the equivalent SendCloud steps once they're confirmed
