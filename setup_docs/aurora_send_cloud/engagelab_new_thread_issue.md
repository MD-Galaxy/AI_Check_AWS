According to the official product documentation from Aurora SendCloud, this behavior is not a bug or a misconfiguration; it is a strict structural rule built directly into the platform's Inbound Route logic. [1] 
Here is the exact technical explanation and official proof explaining why the system notifies you on Replies/Forwards but drops New Emails: [1, 2] 
------------------------------
## The Official Proof (From Aurora SendCloud Documentation)
The official [Aurora SendCloud Inbound Route Documentation](https://docs.aurorasendcloud.com/docs/route) explicitly states the following operational constraint:

"Note: Emails sent directly to the configured address will not be forwarded by default. Only be processed when the recipient replies to the email you sent." [1] 

## Why the Architecture Operates This Way
Aurora SendCloud enforces this rule by relying on specific standard email mechanisms: [3] 
## 1. Tracking Identifiers vs. Independent Headers

* 
* When using Reply or Forward: When the supplier clicks reply or forward inside their email client (like Gmail or Outlook), their client automatically preserves the original email's context. It inserts hidden RFC identifiers into the header payload—such as In-Reply-To, References, or specialized cryptographic watermarks. Aurora SendCloud parses these incoming headers, successfully matches the reply to the outbound log in your account, and triggers your webhook notification. [2, 4, 5, 6] 
* When starting a "New Email": If the supplier clicks "New Email" and manually pastes your receiving route address into the "To" field, none of these tracking headers are created. The message arrives as a completely clean, unassociated string. Because Aurora SendCloud cannot map this text back to a prior outbound transaction ID, its default filter classifies it as an unauthorized direct email and ignores it. [1, 2, 7] 
* 

## 2. System Protection and Anti-Spam Control
Allowing random "New Emails" straight into an inbound processing route leaves downstream APIs exposed to vulnerabilities. If the route triggered on any incoming email, your server could easily become overwhelmed by:

* 
* Spam loops and automated out-of-office notifications.
* Mail bombing targeting your webhook endpoint.
* Data spoofing attacks where malicious actors guess your route address to update supplier records illegitimately. [8, 9] 
* 

------------------------------
## How to Receive New Emails From Suppliers
If you need your suppliers to be able to compose brand-new emails that your system can still track, you must use one of the two official setups:

   1. Custom Dynamic Reply-To Fields:
   When sending notifications out to suppliers via the SendCloud API, define a unique, trackable address inside the standard reply-to parameter (e.g., suppliername-ticket123@yourdomain.com) instead of a general inbox. Even if a supplier starts a completely new email, as long as they type or copy that distinct address, your backend webhook can parse the prefix string to locate the supplier context. [6, 9, 10] 
   2. Setup a Dedicated Receiving Mail Domain:
   Configure a specific domain in your [Aurora SendCloud Domain Management System](https://www.aurorasendcloud.com/docs/Instructions/Setting/) by pointing your MX Records directly to SendCloud. Once the domain is fully verified, you can construct generalized catch-all inbound expressions that process broader incoming streams rather than strict transactional thread-replies. [5, 11] 

If you would like to adjust this configuration, please let me know:

* 
* Are you routing inbound emails to a Forwarding Email Address or an API Webhook URL?
* What address pattern or expression do you currently have written inside your Inbound Route settings? [1, 5] 
* 

I can guide you through the exact setup steps required to process these messages securely!

[1] [https://docs.aurorasendcloud.com](https://docs.aurorasendcloud.com/docs/route)
[2] [https://servicenowguru.com](https://servicenowguru.com/system-definition/inbound-email-new-reply-forward/)
[3] [https://www.passleader.com](https://www.passleader.com/downloadable/download/sample/sample_id/8053/)
[4] [https://www.getinboxzero.com](https://www.getinboxzero.com/blog/post/reply-vs-reply-all-vs-forward)
[5] [https://docs.aurorasendcloud.com](https://docs.aurorasendcloud.com/docs/route)
[6] [https://docs.aurorasendcloud.com](https://docs.aurorasendcloud.com/docs/webhooks)
[7] [https://opentextbc.ca](https://opentextbc.ca/computerstudies/chapter/email-2/)
[8] [https://docs.aurorasendcloud.com](https://docs.aurorasendcloud.com/docs/webhooks)
[9] [https://docs.oracle.com](https://docs.oracle.com/en/cloud/saas/procurement/25d/oaprc/how-you-configure-sender-name-and-email-in-supplier-qualification-notifications.html)
[10] [https://www.sendcloud.net](https://www.sendcloud.net/doc/en/faq/)
[11] [https://www.aurorasendcloud.com](https://www.aurorasendcloud.com/docs/Instructions/Setting/)
