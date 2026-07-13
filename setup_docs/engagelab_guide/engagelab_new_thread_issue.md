## The reason EngageLab's Inbound Mail Routing system triggers notifications when a supplier responds via the Reply or Forward button, but fails to recognize or reply when they start a New Email, comes down to standard email architectural protocols (RFC standards) and webhook processing rules.

## 1. The Core Reason: Missing Thread Metadata (In-Reply-To & References)

When EngageLab routes emails, it looks for specific hidden tracking identifiers in the email headers to tie the incoming message to an existing transaction or ticket. [1]

-
- Using the Reply or Forward Button: The supplier's email client automatically retains the unique Message-ID of the original email. It injects this ID into hidden headers known as In-Reply-To and References, or attaches specific subject line prefixes (like RE:). EngageLab’s parser scans these headers, matches the reply to your account route, and successfully triggers the designated notification webhook. [1, 2]
- Starting a "New Email": When a supplier clicks "New Email" and manually types in your routing address, none of this metadata exists. The email client treats it as an independent, unthreaded communication string. Because there is no data pointing back to the initial transaction, EngageLab cannot securely validate or match the context, resulting in a dropped or unhandled route event. [1]
-

## 2. How EngageLab's Inbound System Works (Official API Context)

According to official [EngageLab Inbound Mail Routing API Specifications](https://www.engagelab.com/docs/email/rest-api/route), inbound traffic relies heavily on structured expressions and automated webhooks: [2]

-
- The Route Evaluation Engine: When an email hits the platform, EngageLab parses the payload based on a configured expression (matching rules) and sends the processed data to a target receiving route action URL. [2]
- The "Watermark" Security Catch: Like most standard enterprise systems, automated communication routing blocks arbitrary "new" emails sent directly to the inbound endpoint to prevent spam loops, mail bombing, and unauthorized updates to external supplier data. A new thread bypasses the required tokenization or watermark logic, meaning it fails the route validation criteria. [1, 3, 4]
-

---

## How to Fix This Workflow

If you need suppliers to be able to initiate clean inquiries, you can use these verified solutions to adjust your architecture:

1.  Implement Inbound Catch-All Catching: Update your expression criteria within the EngageLab Inbound Route Dashboard to look strictly at the recipient prefix (e.g., supplier-incoming@yourdomain.com) rather than requiring strict subject line or thread matching. [2, 5]
2.  Utilize X-SMTPAPI Extensions: Ensure your outbound supplier notifications leverage [EngageLab X-SMTPAPI Extended Fields](https://www.engagelab.com/docs/email/smtp/x-smtpapi--extended-fields). By appending tracking metadata directly into custom headers or unique, dynamically generated Reply-To addresses (e.g., reply-ticket123@yourdomain.com), any email sent to that specific mailbox—even a newly composed one—will route correctly back into your ecosystem. [6]

If you are currently setting up these routes, tell me:

-
- What conditions or expressions are currently configured inside your EngageLab inbound rules?
- Are you handling the parsed email content via REST API webhooks or an internal CRM system?
-

I can provide the exact JSON block or rule structure to help you configure a broader filtering fallback!

[1] [https://www.servicenow.com](https://www.servicenow.com/community/developer-forum/reply-to-an-email-in-inbound-action/m-p/2593866)
[2] [https://www.engagelab.com](https://www.engagelab.com/docs/email/rest-api/route)
[3] [https://mailmeteor.com](https://mailmeteor.com/glossary/looping-mail)
[4] [https://elasticemail.com](https://elasticemail.com/blog/inbound-email-routing)
[5] [https://docs.oracle.com](https://docs.oracle.com/en/cloud/saas/procurement/25d/oaprc/how-you-configure-sender-name-and-email-in-supplier-qualification-notifications.html)
[6] [https://www.engagelab.com](https://www.engagelab.com/docs/email/smtp/x-smtpapi--extended-fields)
