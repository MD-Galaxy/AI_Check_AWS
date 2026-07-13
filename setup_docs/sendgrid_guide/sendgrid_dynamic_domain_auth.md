# SendGrid — Complete Setup Guide
### jobsetu.online · Dynamic From + Reply-To · Domain-Level Auth Only · No Sender Verification

> **Goal:** Send emails FROM dynamically generated addresses like
> `james_42@mail.jobsetu.online` with a dynamic Reply-To — using
> **domain-level authentication only**. No individual sender verification needed.
>
> Domain: **jobsetu.online** | DNS Provider: **Hostinger hPanel**

---

## Why Domain Auth Skips Sender Verification

> This is the most important concept in this guide.

```
❌ Individual Sender Verification (old approach):
   Verify noreply@jobsetu.online → only that address can send
   Verify user42@jobsetu.online  → only that address can send
   Problem: You need to verify EVERY dynamic address — impossible.

✅ Domain Authentication (this guide):
   Verify the domain: mail.jobsetu.online → ALL addresses on it can send
   james_42@mail.jobsetu.online     ← works ✅ (no extra verification)
   user_3fa9c1b2@mail.jobsetu.online ← works ✅ (no extra verification)
   anyprefix_anything@mail.jobsetu.online ← works ✅
   Solution: Verify once, send from any prefix forever.
```

**The key:** Authenticate `mail.jobsetu.online` as the sending subdomain in SendGrid.
After that, every `*@mail.jobsetu.online` address is authorized to send.

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Authenticate Sending Subdomain in SendGrid](#step-1-authenticate-sending-subdomain-in-sendgrid)
3. [Add CNAME Records in Hostinger](#step-2-add-cname-records-in-hostinger)
4. [Set Up MX Record for Inbound](#step-3-set-up-mx-record-for-inbound)
5. [Configure Inbound Parse in SendGrid](#step-4-configure-inbound-parse-in-sendgrid)
6. [Generate Dynamic Email Addresses](#step-5-generate-dynamic-email-addresses)
7. [Send with Dynamic From + Reply-To](#step-6-send-with-dynamic-from--reply-to)
8. [Receive + Track Inbound Replies](#step-7-receive--track-inbound-replies)
9. [Full Working Code](#step-8-full-working-code)
10. [Testing Your Setup](#step-9-testing-your-setup)
11. [Troubleshooting](#step-10-troubleshooting)

---

## Prerequisites

- [x] Domain `jobsetu.online` registered on Hostinger ✅
- [x] Access to Hostinger hPanel → https://hpanel.hostinger.com ✅
- [ ] SendGrid account → https://sendgrid.com (free tier is fine)
- [ ] Python 3.9+ installed
- [ ] Public HTTPS URL for webhook (use ngrok for local dev)

```bash
pip install sendgrid fastapi uvicorn python-multipart
```

---

## STEP 1: Authenticate Sending Subdomain in SendGrid

> **Why authenticate a subdomain and not the root domain?**
> You want to send FROM `*@mail.jobsetu.online`.
> Authenticating `mail.jobsetu.online` directly means SendGrid
> authorizes every address on that exact subdomain — no individual
> verification needed for any dynamic prefix.

---

### 1.1 — Open Domain Authentication

```
Log in → https://app.sendgrid.com

Left sidebar:
  Settings
    └── Sender Authentication
          └── Click "Authenticate Your Domain"
```

---

### 1.2 — Select DNS Provider

```
Screen: "Which DNS provider do you use?"

  ● Cloudflare
  ● GoDaddy
  ● Amazon Route 53
  ● Namecheap
  ● Other    ← SELECT THIS
             (Hostinger is not listed — "Other" works for any provider)

Checkbox: "Would you also like to set up link branding?"
  → Leave UNCHECKED

Click: "Next"
```

---

### 1.3 — Enter the Sending Subdomain

```
Screen: "Which domain do you want to authenticate?"

┌─────────────────────────────────────────────────────────────┐
│                                                             │
│  Domain:                                                    │
│  ┌──────────────────────────────┐                          │
│  │  mail.jobsetu.online         │  ← TYPE THIS EXACTLY     │
│  └──────────────────────────────┘                          │
│                                                             │
│  ⚠️  CRITICAL: Enter the SUBDOMAIN, not the root domain    │
│     ✅ Enter:  mail.jobsetu.online                         │
│     ❌ Do not: jobsetu.online                              │
│                                                             │
│  Why: Authenticating mail.jobsetu.online means SendGrid     │
│  authorizes ALL *@mail.jobsetu.online addresses.            │
│  This is what allows dynamic From without sender verify.    │
│                                                             │
│  Advanced Settings:                                         │
│    "Use automated security"  → ON  ✅                      │
│    "Custom Return Path"      → Leave blank                  │
│    "Custom DKIM selector"    → Leave blank                  │
│                                                             │
│  Click: "Next"                                             │
└─────────────────────────────────────────────────────────────┘
```

---

### 1.4 — Copy CNAME Records from SendGrid

SendGrid now shows you **3 CNAME records**. They will look like this:

```
┌─────────────────────────────────────────────────────────────────────┐
│ SendGrid DNS Records (your values will differ — copy EXACTLY):      │
│                                                                     │
│ Type   Host                                Value                    │
│ ─────  ──────────────────────────────────  ───────────────────────  │
│ CNAME  em1234.mail.jobsetu.online          u1234.wl.sendgrid.net    │
│ CNAME  s1._domainkey.mail.jobsetu.online   s1.domainkey.u1234...    │
│ CNAME  s2._domainkey.mail.jobsetu.online   s2.domainkey.u1234...    │
└─────────────────────────────────────────────────────────────────────┘

⚠️  Your actual em1234 number and u1234 values WILL BE DIFFERENT.
    Copy EXACTLY what SendGrid shows on your screen.
    Keep this SendGrid tab open — you'll need these values next.
```

---

## STEP 2: Add CNAME Records in Hostinger

> Open Hostinger in a **new tab** so you can copy values from SendGrid
> without losing your place.

```
Log in → https://hpanel.hostinger.com
→ Domains (left sidebar)
→ Click: jobsetu.online
→ Click: DNS / Nameservers tab
```

---

### 2.1 — Add CNAME Record 1 (Return Path)

```
Click: "Add Record"

Type:       CNAME
Name:       em1234.mail          ← Prefix only — DO NOT include .jobsetu.online
                                    Hostinger appends it automatically.
                                    If SendGrid shows: em1234.mail.jobsetu.online
                                    Enter ONLY:        em1234.mail
Points to:  u1234.wl.sendgrid.net  ← EXACT value from SendGrid
TTL:        14400

Click: "Add Record"
```

---

### 2.2 — Add CNAME Record 2 (DKIM Key 1)

```
Click: "Add Record"

Type:       CNAME
Name:       s1._domainkey.mail   ← Prefix only (no .jobsetu.online)
Points to:  s1.domainkey.u1234.wl.sendgrid.net
TTL:        14400

Click: "Add Record"
```

---

### 2.3 — Add CNAME Record 3 (DKIM Key 2)

```
Click: "Add Record"

Type:       CNAME
Name:       s2._domainkey.mail   ← Prefix only (no .jobsetu.online)
Points to:  s2.domainkey.u1234.wl.sendgrid.net
TTL:        14400

Click: "Add Record"
```

> ⚠️  **Hostinger-specific rule:**
> The Name field must NOT include `.jobsetu.online` — Hostinger appends it.
> Wrong: `em1234.mail.jobsetu.online`
> Right: `em1234.mail`

---

### 2.4 — Verify Domain in SendGrid

```
Back in SendGrid tab:
→ Click "I've added these records"
→ Click "Verify"

✅ All 3 records show green checkmarks
   → Domain mail.jobsetu.online is now authenticated
   → Every *@mail.jobsetu.online address can now send
   → No individual sender verification needed from this point

❌ If red / fails:
   → Hostinger DNS changes take 15–60 min to propagate
   → Check https://dnschecker.org for each CNAME
   → Ensure Name field has NO .jobsetu.online suffix
   → Try again after 30 minutes
```

**Verify propagation from terminal:**

```bash
dig CNAME em1234.mail.jobsetu.online
# Expected: em1234.mail.jobsetu.online. 300 IN CNAME u1234.wl.sendgrid.net.

dig CNAME s1._domainkey.mail.jobsetu.online
# Expected: s1._domainkey.mail.jobsetu.online. 300 IN CNAME s1.domainkey...
```

> 💡 Browser alternative: https://dnschecker.org
> Enter each CNAME → green ticks = propagated globally.

---

## STEP 3: Set Up MX Record for Inbound

> The MX record tells the internet: "Emails sent TO *@mail.jobsetu.online
> should be delivered to SendGrid's servers."
> Without this, supplier replies have nowhere to go.

---

### 3.1 — Add MX Record in Hostinger

```
Hostinger hPanel
→ jobsetu.online → DNS / Nameservers → Add Record

Type:       MX
Name:       mail                 ← Prefix only, creates mail.jobsetu.online
Points to:  mx.sendgrid.net
Priority:   10
TTL:        14400

Click: "Add Record"
```

> ⚠️  Do NOT add MX to the root domain (`@` or blank Name field).
> That would break your existing Hostinger email accounts.
> The Name field MUST be `mail` only.

---

### 3.2 — Verify MX Record is Live

```bash
dig MX mail.jobsetu.online
# Expected: mail.jobsetu.online. 300 IN MX 10 mx.sendgrid.net.
```

> 💡 Or use https://mxtoolbox.com → Enter `mail.jobsetu.online` → MX Lookup
> Do not proceed to Step 4 until MX shows live.

---

## STEP 4: Configure Inbound Parse in SendGrid

> This tells SendGrid: "When an email arrives at any address
> @mail.jobsetu.online, POST the full parsed email to my webhook URL."

---

### 4.1 — Open Inbound Parse

```
SendGrid Dashboard
  Settings
    └── Inbound Parse
          └── Click "Add Host & URL"
```

---

### 4.2 — Configure the Inbound Parse Webhook

```
┌──────────────────────────────────────────────────────────────┐
│                                                              │
│  Receiving Domain:                                           │
│  ┌──────────────────────────────────────────┐               │
│  │  mail.jobsetu.online                     │               │
│  └──────────────────────────────────────────┘               │
│  ↑ Must exactly match your MX record subdomain              │
│                                                             │
│  Destination URL:                                            │
│  ┌──────────────────────────────────────────┐               │
│  │  https://yourapp.com/webhooks/inbound    │               │
│  └──────────────────────────────────────────┘               │
│  ↑ Must be HTTPS and publicly accessible                    │
│  ↑ For local dev: use your ngrok URL                        │
│                                                             │
│  ☑  Check incoming emails for spam                          │
│  ☐  POST the raw, full MIME message  ← Leave UNCHECKED     │
│                                                             │
│  Click: "Add"                                              │
└──────────────────────────────────────────────────────────────┘
```

---

### 4.3 — Local Development with ngrok

```bash
# Start your FastAPI app
uvicorn main:app --port 8000

# In a second terminal — expose it publicly
ngrok http 8000

# ngrok gives you a public HTTPS URL:
# https://3f4a-1234-abcd.ngrok.io

# Use this as your SendGrid Destination URL:
# https://3f4a-1234-abcd.ngrok.io/webhooks/inbound
```

> ⚠️  ngrok URLs change every restart.
> Update the Inbound Parse URL each time you restart ngrok.

---

## STEP 5: Generate Dynamic Email Addresses

> With domain authentication complete, SendGrid authorizes every
> `*@mail.jobsetu.online` address. You can generate as many
> unique addresses as needed — no limit, no verification.

```python
# ─────────────────────────────────────────────────────────────
# dynamic_address.py
# ─────────────────────────────────────────────────────────────

import uuid
import re

INBOUND_DOMAIN = "mail.jobsetu.online"


def generate_unique_id() -> str:
    """Generate a short unique ID for a conversation."""
    return str(uuid.uuid4()).replace("-", "")[:8]   # e.g. "3fa9c1b2"


def build_dynamic_email(username: str, unique_id: str) -> str:
    """
    Build a dynamic email address.

    Pattern: {username}_{unique_id}@mail.jobsetu.online

    Examples:
        build_dynamic_email("james", "42")
        → james_42@mail.jobsetu.online

        build_dynamic_email("raj", "3fa9c1b2")
        → raj_3fa9c1b2@mail.jobsetu.online
    """
    return f"{username}_{unique_id}@{INBOUND_DOMAIN}"


def parse_dynamic_email(raw_address: str) -> dict | None:
    """
    Extract username and unique_id from a dynamic email address.

    Handles all common formats:
      "james_42@mail.jobsetu.online"
      "<james_42@mail.jobsetu.online>"
      "James <james_42@mail.jobsetu.online>"

    Returns:
      {"username": "james", "unique_id": "42"}  or  None
    """
    # Strip display name and angle brackets
    match = re.search(r'[\w._%+\-]+@[\w.\-]+', raw_address)
    if not match:
        return None

    email = match.group(0).lower()

    # Parse username_uniqueid pattern
    pattern = rf'^([a-z0-9]+)_([a-z0-9]+)@{re.escape(INBOUND_DOMAIN)}$'
    m = re.match(pattern, email)

    if m:
        return {
            "username":  m.group(1),
            "unique_id": m.group(2)
        }
    return None


# ── Test ──────────────────────────────────────────────────────
if __name__ == "__main__":
    uid = generate_unique_id()
    addr = build_dynamic_email("james", uid)
    print(f"Generated: {addr}")             # james_3fa9c1b2@mail.jobsetu.online
    print(f"Parsed:    {parse_dynamic_email(addr)}")
    # {'username': 'james', 'unique_id': '3fa9c1b2'}
```

---

## STEP 6: Send with Dynamic From + Reply-To

> **Core sending logic.** Both From and Reply-To use the same dynamic
> address. Domain authentication covers both — no extra steps needed.

```python
# ─────────────────────────────────────────────────────────────
# email_sender.py
# ─────────────────────────────────────────────────────────────

import sendgrid
from sendgrid.helpers.mail import (
    Mail, From, To, ReplyTo,
    Subject, HtmlContent, PlainTextContent
)

SENDGRID_API_KEY = "YOUR_SENDGRID_API_KEY"
INBOUND_DOMAIN   = "mail.jobsetu.online"

sg = sendgrid.SendGridAPIClient(api_key=SENDGRID_API_KEY)


def send_email(
    username: str,
    unique_id: str,
    to_email: str,
    to_name: str,
    subject: str,
    html_body: str,
    plain_body: str = ""
) -> dict:
    """
    Send email with BOTH dynamic From and dynamic Reply-To.

    From:     {username}_{unique_id}@mail.jobsetu.online  ← DYNAMIC
    Reply-To: {username}_{unique_id}@mail.jobsetu.online  ← DYNAMIC

    No sender verification needed — mail.jobsetu.online is
    domain-authenticated, covering ALL prefixes on this domain.

    Args:
        username:   User's identifier (e.g. "james")
        unique_id:  Conversation unique ID (e.g. "42" or "3fa9c1b2")
        to_email:   Recipient email address
        to_name:    Recipient display name
        subject:    Email subject
        html_body:  HTML content
        plain_body: Plain text fallback

    Returns:
        dict: status_code, from_email, reply_to, message_id
    """

    # Both From and Reply-To are the same dynamic address
    dynamic_address = f"{username}_{unique_id}@{INBOUND_DOMAIN}"

    message = Mail()
    message.from_email   = From(dynamic_address, "Jobsetu Sourcing")  # ← DYNAMIC
    message.reply_to     = ReplyTo(dynamic_address)                    # ← DYNAMIC
    message.to           = To(to_email, to_name)
    message.subject      = Subject(subject)
    message.html_content = HtmlContent(html_body)

    if plain_body:
        message.plain_text_content = PlainTextContent(plain_body)

    response = sg.send(message)

    print(f"[Email Sent]")
    print(f"  From:     {dynamic_address}  ← dynamic, no verification needed")
    print(f"  Reply-To: {dynamic_address}  ← dynamic, tracks supplier replies")
    print(f"  To:       {to_email}")
    print(f"  Status:   {response.status_code}")    # 202 = accepted

    return {
        "status_code":  response.status_code,
        "from_email":   dynamic_address,
        "reply_to":     dynamic_address,
        "to":           to_email,
        "message_id":   response.headers.get("X-Message-Id", "")
    }


def build_rfq_html(
    username: str,
    unique_id: str,
    supplier_name: str,
    product_name: str,
    quantity: int,
    target_price: str
) -> str:
    """Build RFQ email HTML body."""
    ref = f"{username}_{unique_id}"

    return f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px;">

        <p>Dear {supplier_name},</p>

        <p>We are requesting a formal quotation for the following:</p>

        <table border="1" cellpadding="10" cellspacing="0"
               style="border-collapse:collapse; width:100%;">
            <thead style="background:#f5f5f5;">
                <tr>
                    <th>Product</th>
                    <th>Quantity</th>
                    <th>Target Price</th>
                </tr>
            </thead>
            <tbody>
                <tr>
                    <td>{product_name}</td>
                    <td>{quantity:,} units</td>
                    <td>{target_price} per unit</td>
                </tr>
            </tbody>
        </table>

        <p>Please include in your response:</p>
        <ul>
            <li>Unit price (FOB)</li>
            <li>Minimum Order Quantity (MOQ)</li>
            <li>Lead time</li>
            <li>Payment terms</li>
        </ul>

        <p>Kindly respond within <strong>3 business days</strong>.</p>

        <p>Best regards,<br>
        <strong>Jobsetu Sourcing Team</strong></p>

        <hr style="border:none; border-top:1px solid #eee; margin-top:30px;">
        <p style="font-size:11px; color:#aaa;">Ref: {ref}</p>
    </div>
    """


# ── Usage ─────────────────────────────────────────────────────
if __name__ == "__main__":
    from dynamic_address import generate_unique_id

    username  = "james"
    unique_id = generate_unique_id()    # e.g. "3fa9c1b2"

    html = build_rfq_html(
        username      = username,
        unique_id     = unique_id,
        supplier_name = "Acme Electronics",
        product_name  = "Bluetooth Speaker X200",
        quantity      = 500,
        target_price  = "$12.00"
    )

    result = send_email(
        username  = username,
        unique_id = unique_id,
        to_email  = "purchasing@acme-electronics.com",
        to_name   = "Acme Electronics",
        subject   = f"[RFQ-{unique_id[:4].upper()}] Bluetooth Speaker X200",
        html_body = html,
        plain_body= f"RFQ for Bluetooth Speaker X200 — Ref: {username}_{unique_id}"
    )

# Console output:
# [Email Sent]
#   From:     james_3fa9c1b2@mail.jobsetu.online  ← dynamic, no verification needed
#   Reply-To: james_3fa9c1b2@mail.jobsetu.online  ← dynamic, tracks supplier replies
#   To:       purchasing@acme-electronics.com
#   Status:   202
```

---

## STEP 7: Receive + Track Inbound Replies

```python
# ─────────────────────────────────────────────────────────────
# webhook_handler.py
# ─────────────────────────────────────────────────────────────

from fastapi import FastAPI, Request
from datetime import datetime
import re

app = FastAPI()

INBOUND_DOMAIN = "mail.jobsetu.online"


def parse_dynamic_email(raw_address: str) -> dict | None:
    """Extract username and unique_id from inbound To address."""
    match = re.search(r'[\w._%+\-]+@[\w.\-]+', raw_address)
    if not match:
        return None
    email = match.group(0).lower()
    pattern = rf'^([a-z0-9]+)_([a-z0-9]+)@{re.escape(INBOUND_DOMAIN)}$'
    m = re.match(pattern, email)
    return {"username": m.group(1), "unique_id": m.group(2)} if m else None


@app.post("/webhooks/inbound")
async def handle_inbound_email(request: Request):
    """
    SendGrid calls this endpoint when a supplier replies to any
    *@mail.jobsetu.online address.

    SendGrid Inbound Parse provides these fields:
      from        → supplier's email address
      to          → the dynamic address (james_42@mail.jobsetu.online)
      subject     → email subject
      text        → plain text body
      html        → HTML body
      headers     → raw email headers
      spam_score  → spam score (float as string)
      dkim        → DKIM validation result
      SPF         → SPF check result
    """

    data = await request.form()

    # ── Extract fields ────────────────────────────────────────
    from_email  = data.get("from", "")
    to_email    = data.get("to", "")
    subject     = data.get("subject", "")
    body_text   = data.get("text", "")
    body_html   = data.get("html", "")
    spam_score  = float(data.get("spam_score", "0") or "0")
    dkim        = data.get("dkim", "")
    spf         = data.get("SPF", "")
    received_at = datetime.utcnow().isoformat()

    print(f"\n[Inbound Email — {received_at}]")
    print(f"  From:    {from_email}")
    print(f"  To:      {to_email}")
    print(f"  Subject: {subject}")

    # ── Spam filter ───────────────────────────────────────────
    if spam_score > 5.0:
        print(f"  ⚠️  Spam score {spam_score} — skipping")
        return {"status": "skipped", "reason": "spam"}

    # ── Parse username + unique_id ────────────────────────────
    parsed = parse_dynamic_email(to_email)

    if not parsed:
        print(f"  ❌ Could not parse address: {to_email}")
        # Log for manual review
        # db.unmatched_emails.insert({...})
        return {"status": "unmatched"}

    username  = parsed["username"]
    unique_id = parsed["unique_id"]
    print(f"  ✅ Matched → username: {username}, unique_id: {unique_id}")

    # ── Look up user + conversation in DB ─────────────────────
    # user         = db.users.find(username=username)
    # conversation = db.conversations.find(unique_id=unique_id)

    # ── Save inbound reply ────────────────────────────────────
    # db.emails_received.insert({
    #     "unique_id":   unique_id,
    #     "username":    username,
    #     "from_email":  from_email,
    #     "to_email":    to_email,
    #     "subject":     subject,
    #     "body_text":   body_text,
    #     "body_html":   body_html,
    #     "dkim":        dkim,
    #     "spf":         spf,
    #     "received_at": received_at
    # })

    # ── Update conversation status ────────────────────────────
    # db.conversations.update(
    #     {"unique_id": unique_id},
    #     {"status": "replied", "last_reply_at": received_at}
    # )

    # ── Classify supplier reply ───────────────────────────────
    action = classify_reply(body_text)
    print(f"  🤖 Action: {action}")

    # ── Trigger agent / notify user ───────────────────────────
    # agent.invoke({
    #     "username":   username,
    #     "unique_id":  unique_id,
    #     "action":     action,
    #     "from":       from_email,
    #     "reply_body": body_text
    # })

    return {
        "status":    "processed",
        "username":  username,
        "unique_id": unique_id,
        "action":    action
    }


def classify_reply(body: str) -> str:
    """Classify supplier reply into an agent action."""
    body_lower = body.lower()

    if any(w in body_lower for w in ["price", "quote", "usd", "$", "per unit"]):
        return "QUOTE_RECEIVED"
    elif any(w in body_lower for w in ["sorry", "cannot", "unable", "no stock"]):
        return "SUPPLIER_DECLINED"
    elif any(w in body_lower for w in ["question", "clarif", "please confirm", "?"]):
        return "CLARIFICATION_NEEDED"
    elif any(w in body_lower for w in ["out of office", "auto-reply", "on vacation"]):
        return "AUTO_RESPONDER"
    else:
        return "MANUAL_REVIEW"
```

---

## STEP 8: Full Working Code

```python
# ─────────────────────────────────────────────────────────────
# main.py — End-to-end example
# ─────────────────────────────────────────────────────────────

import uuid
import sendgrid
from sendgrid.helpers.mail import Mail, From, To, ReplyTo, Subject, HtmlContent

SENDGRID_API_KEY = "YOUR_SENDGRID_API_KEY"
INBOUND_DOMAIN   = "mail.jobsetu.online"

sg = sendgrid.SendGridAPIClient(api_key=SENDGRID_API_KEY)


def generate_unique_id() -> str:
    return str(uuid.uuid4()).replace("-", "")[:8]


def build_dynamic_email(username: str, unique_id: str) -> str:
    return f"{username}_{unique_id}@{INBOUND_DOMAIN}"


def send_rfq(username: str, unique_id: str, supplier_email: str, product: str):
    """Send RFQ with fully dynamic From + Reply-To."""

    dynamic_address = build_dynamic_email(username, unique_id)

    html = f"""
        <h2>Request for Quotation</h2>
        <p>Please quote for: <strong>{product}</strong></p>
        <p>Reply within 3 business days.</p>
        <hr>
        <small>Ref: {username}_{unique_id}</small>
    """

    message = Mail()
    message.from_email   = From(dynamic_address, "Jobsetu Sourcing")  # ← DYNAMIC
    message.reply_to     = ReplyTo(dynamic_address)                    # ← DYNAMIC
    message.to           = To(supplier_email)
    message.subject      = Subject(f"RFQ — {product}")
    message.html_content = HtmlContent(html)

    response = sg.send(message)

    print(f"\n✅ RFQ Sent!")
    print(f"   From (dynamic):     {dynamic_address}")
    print(f"   Reply-To (dynamic): {dynamic_address}")
    print(f"   To:                 {supplier_email}")
    print(f"   Status:             {response.status_code}")

    return response.status_code


# ── Run ───────────────────────────────────────────────────────

username  = "james"
unique_id = generate_unique_id()        # → e.g. "3fa9c1b2"

send_rfq(
    username       = username,
    unique_id      = unique_id,
    supplier_email = "purchasing@acme.com",
    product        = "Bluetooth Speaker X200"
)

# ─── What happens next ───────────────────────────────────────
# From:     james_3fa9c1b2@mail.jobsetu.online (dynamic ✅)
# Reply-To: james_3fa9c1b2@mail.jobsetu.online (dynamic ✅)
# No sender verification error (domain auth covers all prefixes ✅)
#
# Supplier hits Reply
# → Goes to: james_3fa9c1b2@mail.jobsetu.online
# → MX record routes to SendGrid
# → Inbound Parse POSTs to /webhooks/inbound
# → Webhook extracts username=james, unique_id=3fa9c1b2
# → Triggers negotiation agent


# ─── Start webhook server ────────────────────────────────────
# uvicorn webhook_handler:app --host 0.0.0.0 --port 8000 --reload
```

---

## STEP 9: Testing Your Setup

### Test 1: Verify CNAMEs Are Live

```bash
dig CNAME em1234.mail.jobsetu.online
dig CNAME s1._domainkey.mail.jobsetu.online
dig CNAME s2._domainkey.mail.jobsetu.online

# All 3 should return CNAME → sendgrid.net values
```

### Test 2: Verify MX Record

```bash
dig MX mail.jobsetu.online
# Expected: mail.jobsetu.online. 300 IN MX 10 mx.sendgrid.net.
```

### Test 3: Send From a Dynamic Address

```python
import sendgrid
from sendgrid.helpers.mail import Mail, From, ReplyTo

sg = sendgrid.SendGridAPIClient(api_key="YOUR_API_KEY")

# Test with a random dynamic address
test_from = "testuser_abc123@mail.jobsetu.online"

message = Mail(
    from_email    = From(test_from, "Test"),
    to_emails     = "your-personal@gmail.com",
    subject       = "Dynamic From Test",
    html_content  = "<h1>Dynamic From is working!</h1>"
)
message.reply_to = ReplyTo(test_from)

response = sg.send(message)
print(response.status_code)    # 202 = success, no verification error ✅
```

### Test 4: Test Inbound Webhook

```bash
# Simulate SendGrid posting to your webhook
curl -X POST http://localhost:8000/webhooks/inbound \
  --data-urlencode "from=supplier@acme.com" \
  --data-urlencode "to=james_42@mail.jobsetu.online" \
  --data-urlencode "subject=Re: RFQ Bluetooth Speakers" \
  --data-urlencode "text=Our price is $11.50 per unit FOB Shenzhen."

# Expected:
# {"status":"processed","username":"james","unique_id":"42","action":"QUOTE_RECEIVED"}
```

### Test 5: End-to-End Loop

```
1. Run: python main.py
   → Email sent FROM james_3fa9c1b2@mail.jobsetu.online

2. Check your Gmail — email arrives from that dynamic address

3. Hit Reply in Gmail

4. Reply goes to: james_3fa9c1b2@mail.jobsetu.online
   → SendGrid catches it (MX record)
   → POSTs to your ngrok URL → /webhooks/inbound
   → Webhook prints: username=james, unique_id=3fa9c1b2 ✅
```

---

## STEP 10: Troubleshooting

| Problem | Cause | Fix |
|---|---|---|
| "Sender not verified" error | Domain not authenticated yet | Complete Step 1 fully — all 3 CNAMEs must be green |
| "Sender not verified" after domain auth | Entered root domain instead of subdomain | Delete and re-authenticate — enter `mail.jobsetu.online` not `jobsetu.online` |
| CNAME verification fails | `.jobsetu.online` suffix in Hostinger Name field | In Hostinger, enter prefix only e.g. `em1234.mail` not `em1234.mail.jobsetu.online` |
| CNAME fails after 2 hours | DNS still propagating | Check https://dnschecker.org → CNAME for `em1234.mail.jobsetu.online` |
| MX record not found | DNS delay or wrong Name field | Name must be `mail` only, not `@` or `jobsetu.online` |
| Inbound webhook not firing | Wrong domain in Inbound Parse | Inbound Parse receiving domain must be exactly `mail.jobsetu.online` |
| `parse_dynamic_email` returns None | Display name not stripped | Use `re.search(r'[\w._%+\-]+@[\w.\-]+', raw)` to extract email first |
| Status 202 but email in spam | SPF / DKIM not set up | Ensure all 3 CNAME records are verified green in SendGrid |
| ngrok webhook stops working | ngrok session expired | Restart ngrok and update SendGrid Inbound Parse URL |

---

### Common Fix: "Sender not verified" after domain auth

This error means SendGrid still sees the From address as unverified. Root causes:

```
Cause 1: You authenticated jobsetu.online (root domain)
         But you're sending FROM *@mail.jobsetu.online (subdomain)
         → These don't match

Fix:     Re-authenticate — enter mail.jobsetu.online (not jobsetu.online)
         in Step 1.3

─────────────────────────────────────────────────────────────

Cause 2: Domain auth completed but CNAMEs not fully propagated
         SendGrid still sees the domain as unverified

Fix:     Wait 1-4 hours, check dnschecker.org for all 3 CNAMEs,
         then re-verify in SendGrid

─────────────────────────────────────────────────────────────

Cause 3: API Key has restricted permissions

Fix:     Settings → API Keys → Your Key → Edit
         → Set to "Full Access" or ensure "Mail Send" is enabled
```

---

## Summary: What You've Built

```
┌──────────────────────────────────────────────────────────────┐
│                                                              │
│  DOMAIN AUTH (one-time setup)                                │
│  Authenticate: mail.jobsetu.online → all prefixes covered   │
│  No individual verification ever again ✅                    │
│                                                              │
│  OUTBOUND                                                    │
│  From:     james_42@mail.jobsetu.online  ← DYNAMIC ✅       │
│  Reply-To: james_42@mail.jobsetu.online  ← DYNAMIC ✅       │
│                     │                                        │
│              ┌──────▼────────────┐                          │
│  SendGrid    │  Sends via DKIM + │ → supplier@acme.com      │
│  (auth ✅)   │  SPF verified     │                          │
│              └───────────────────┘                          │
│                                                              │
│  SUPPLIER hits Reply                                         │
│    → Goes to: james_42@mail.jobsetu.online                  │
│                     │                                        │
│              ┌──────▼────────────┐                          │
│  MX record   │  mx.sendgrid.net  │ ← catches *@mail.job... │
│              └──────┬────────────┘                          │
│                     │                                        │
│              ┌──────▼────────────┐                          │
│  Inbound     │ POST /webhooks/   │ ← SendGrid fires webhook │
│  Parse       │ inbound           │                          │
│              └──────┬────────────┘                          │
│                     │                                        │
│              ┌──────▼────────────┐                          │
│  Webhook     │ username = james  │                          │
│  parses      │ unique_id = 42    │                          │
│              └──────┬────────────┘                          │
│                     │                                        │
│              ┌──────▼────────────┐                          │
│  LangGraph   │ Negotiation agent │                          │
│  Agent       │ Follow-up agent   │                          │
│              └───────────────────┘                          │
└──────────────────────────────────────────────────────────────┘
```

---

*Generated: June 2026 | Domain: jobsetu.online | DNS: Hostinger hPanel | SendGrid API v3 | FastAPI | Python 3.11+*
