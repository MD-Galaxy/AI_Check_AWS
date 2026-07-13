# EngageLab — Complete Reference & Implementation Guide

*What it is, API setup, and exactly how this repo uses it*

This document serves as the implementation blueprint for replacing or complementing
the email infrastructure with EngageLab as of July 6, 2026.
It covers subdomain registration, sending via dynamic sender addresses without pre-registering
each prefix, and catching incoming supplier replies via Inbound Webhooks.

Official Docs: EngageLab Email API

## Table of Contents

1. [What Is EngageLab](#1-what-is-engagelab)
   - [1.1 Pricing](#11-pricing)
2. [Data Centers, Base URLs & Auth](#2-data-centers-base-urls--auth)
3. [API_USER & Keys (Dashboard Setup)](#3-api_user--keys-dashboard-setup)
4. [Domain Authentication (SPF / DKIM / MX / Tracking)](#4-domain-authentication-spf--dkim--mx--tracking)
5. [Outbound Sending & Dynamic "From" Addresses](#5-outbound-sending--dynamic-from-addresses)
6. [Inbound Route — Catching Replies via Webhook](#6-inbound-route--catching-replies-via-webhook)
7. [End-to-End Code Flow Integration](#7-end-to-end-code-flow-integration)
8. [Configuration Reference](#8-configuration-reference)
9. [Testing & Local Development](#9-testing--local-development)

## 1. What Is EngageLab

EngageLab is a multi-channel customer engagement platform (Email, SMS, AppPush, WebPush, WhatsApp). For our use case, we are integrating with the EngageLab SendCloud Global Email Delivery Service via REST API.

Key features we utilize:

- **Transactional API (Trigger Emails)** — Sending outbound RFQs using HTTP REST API.
- **Dynamic Sender Identities** — EngageLab allows you to define custom prefixes dynamically at send time, provided the domain suffix is authenticated.
- **Inbound Webhook Routing** — Catching replies to our dynamically generated addresses and pushing them to our `/email_poc/webhooks/inbound` endpoint.
- **API_USER Architecture** — EngageLab isolates sending reputations and webhooks per API_USER entity.

### 1.1 Pricing

| Tier | Volume | Cost |
|---|---|---|
| Free | 50 emails/day | ✅ Free |
| Paid | 10,000 emails/month | $29.90/month |
| Paid | 50,000 emails/month | $127.00/month |

This is the provider used for our China-region POC (see `SUPPLIER_EMAIL_FLOW.md` for the full provider cost comparison).

## 2. Data Centers, Base URLs & Auth

EngageLab operates multi-regional data centers. You must use the Base URL that corresponds to where your account/data center is provisioned.

| Region | Base URL |
|---|---|
| Singapore | `https://email.api.engagelab.cc` |
| Turkey | `https://emailapi-tr.engagelab.com` |

**Authentication Method:** Unlike providers that use standard Bearer tokens, EngageLab requires HTTP Basic Authentication using a base64 encoded string of your `api_user` and `api_key`.

```
Authorization: Basic base64(api_user:api_key)
```

> **Note:** `api_user` is the actual username string created in the dashboard, NOT your EngageLab login email.

## 3. API_USER & Keys (Dashboard Setup)

In EngageLab, you don't just generate a global API key. You create an API_USER.

1. Log into EngageLab → Email → Send Settings → API_USER.
2. Create a new API_USER.
3. **Crucial Selection:** Choose Trigger Email (`email_type: 0`), NOT Batch. Trigger emails are prioritized for transactional delivery (RFQs).
4. Bind this API_USER to your sending subdomain (e.g., `mail.jobsetu.online`).
5. The system will generate an API_KEY for this specific API_USER.
6. Save both the API_USER and API_KEY for your `.env` file.

## 4. Domain Authentication (SPF / DKIM / MX / Tracking)

EngageLab automatically provides a test domain upon registration. Do not use the test domain for production.

To send dynamically from `{CamelCaseName}-{conv_id}@mail.jobsetu.online`, you must authenticate the subdomain `mail.jobsetu.online`.

### Step 1: Add Domain in EngageLab

Go to Send Settings → Domain Management. Add `mail.jobsetu.online`. EngageLab will generate 3 TXT records (for SPF/verification) and 1 MX record.

### Step 2: Configure Hostinger DNS

Go to your Hostinger hPanel → DNS Zone Editor for `jobsetu.online` and add the records for the mail subdomain:

| Record Type | Host / Name | Value / Points to | Purpose |
|---|---|---|---|
| TXT | mail | `v=spf1 include:spf.engagelab.cc -all` (use the exact value provided) | SPF (Sender Policy Framework) |
| TXT | `_domainkey.mail` | (Generated EngageLab DKIM Value) | DKIM Authentication |
| MX | mail | `mxa.engagelab.cc` (Priority 10) | Mandatory for Inbound Routing |
| CNAME | `track.mail` | `track.engagelab.cc` | Custom Tracking Domain (Optional but recommended) |

### Step 3: Verify

Click "Verify" in the EngageLab dashboard. Once status is Usable/Verified, the domain is ready.

## 5. Outbound Sending & Dynamic "From" Addresses

EngageLab handles "Envelope Sender" (`mail from`) and "Header Sender" (`from`).

**The Golden Rule for EngageLab Dynamic Addresses:** Because you verified the suffix `mail.jobsetu.online`, EngageLab allows you to define the prefix dynamically on the fly without pre-registering it.

If your dynamic address is `JamesWhitfield-3fa9c1b2@mail.jobsetu.online`:

- Ensure the suffix exactly matches your verified domain.
- Pass this dynamic address in both the `from` and `reply_to` fields.

**API Endpoint**

```
POST {ENGAGELAB_BASE_URL}/v1/mail/send
Content-Type: application/json
```

**Payload Example**

```json
{
  "from": "EngageLab Team<JamesWhitfield-3fa9c1b2@mail.jobsetu.online>",
  "to": ["supplier@example.com"],
  "body": {
    "reply_to": ["JamesWhitfield-3fa9c1b2@mail.jobsetu.online"],
    "subject": "RFQ: Required Parts",
    "content": {
      "html": "<h1>RFQ Details</h1><p>...</p>"
    },
    "settings": {
      "send_mode": 0
    }
  }
}
```

**Note on `send_mode`:** `0` is for individual transactional emails. Unlike other providers, EngageLab nests `subject`, `content`, `reply_to`, `attachments` and `settings` inside a `body` object — sending them flat at the top level returns `404 not found`.

## 6. Inbound Route — Catching Replies via Webhook

Because your MX records for `mail.jobsetu.online` point to EngageLab, EngageLab's inbound servers will receive supplier replies. We need to forward these to your app.

**Configuration Steps**

1. In EngageLab Dashboard, go to WebHook settings.
2. Add a new Webhook.
3. Events: Select Inbound Email / Reply Received (and deselect click/open tracking if you only want replies).
4. URL: Enter your public endpoint: `https://<your-domain>/email_poc/webhooks/inbound`
5. Binding: Bind this Webhook to the specific API_USER you created in Step 3.

**Wildcard / Catch-All**

Unlike some providers that require regex rules (`.*`), EngageLab routes all inbound emails hitting the bound API_USER's domain to the configured Webhook. Because every generated address ends in `@mail.jobsetu.online`, EngageLab naturally catches and forwards them all.

**Webhook Payload (JSON/Form)**

When a reply arrives, EngageLab posts data to your webhook. You will map these in `EngageLabWebhookParser`:

- `sender` (Supplier's email)
- `recipient` (Your dynamic address: `JamesWhitfield-3fa9c1b2@...`)
- `subject`
- `message` / `html` / `text`
- `attachments` (Base64 arrays)

## 7. End-to-End Code Flow Integration

To add this to the existing architecture:

- **Provider** (`src/email_platform/engagelab_provider.py`) — Extend `EmailMaster`. Implement HTTP Basic Auth logic for `requests.post()`. Ensure `from` and `reply_to` utilize the `self.build_dynamic_email()` method.
- **Parser** (`src/webhook_factory/engagelab_webhook.py`) — Extend `WebhookParserMaster`. Parse EngageLab's specific JSON webhook payload. Extract the `conv_id` from the `recipient` field using `parse_dynamic_email()`.
- **Factory** — Add `engagelab` to `EMAIL_PROVIDER` options in `.env`. The factories will automatically wire up the EngageLab sender and parser.

## 8. Configuration Reference

Add these to your `.env` file:

| Variable | Required | Notes |
|---|---|---|
| `EMAIL_PROVIDER` | ✅ | Set to `engagelab` |
| `ENGAGELAB_API_USER` | ✅ | The API_USER string from dashboard |
| `ENGAGELAB_API_KEY` | ✅ | The API_KEY associated with the API_USER |
| `ENGAGELAB_API_BASE` | ❌ | Default: `https://email.api.engagelab.cc` |
| `INBOUND_DOMAIN` | ✅ | E.g., `mail.jobsetu.online` |

## 9. Testing & Local Development

### Testing Outbound

```bash
curl -X POST "https://email.api.engagelab.cc/v1/mail/send" \
     -H "Authorization: Basic <Base64(API_USER:API_KEY)>" \
     -H "Content-Type: application/json" \
     -d '{
           "from": "JamesWhitfield-3fa9c1b2@mail.jobsetu.online",
           "to": ["test@example.com"],
           "body": {
             "subject": "Test RFQ",
             "content": {
               "html": "<p>This is a test.</p>"
             }
           }
         }'
```

### Testing Inbound Webhook Locally

1. Start Ngrok: `ngrok http 7000`
2. Update EngageLab Webhook URL to: `https://<your-ngrok>.ngrok-free.app/email_poc/webhooks/inbound`
3. Send an email from your personal Gmail to `Test-1234abcd@mail.jobsetu.online`.
4. Watch your local server console to inspect the incoming EngageLab webhook payload and implement the exact key mapping in `engagelab_webhook.py`.
