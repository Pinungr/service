# Messaging deployment and actual capabilities

Core work is offline. Messaging starts in local test-capture mode. This implementation never sends to a real customer during its automated tests or demo generation. No WhatsApp Web scraping, personal-account automation, public webhook listener, tunnel or cloud service is installed.

## Official WhatsApp Cloud API

Create/configure the owner's Meta WhatsApp Business Platform account, business phone number and permissions through Meta. Provide the phone-number ID, a currently supported Graph API version and an authorized token in Settings. Configure an approved template name/language for each business event. This adapter uses an approved template with **one body text variable**, containing the saved customer-facing message. The business must obtain recipient opt-in and Meta template approval. Provider/conversation/template charges and account eligibility are external prerequisites.

The adapter posts templates to `https://graph.facebook.com/{version}/{phone-number-id}/messages` with the messaging product and approved template. It stores the returned provider message ID. There is no invented message-status polling endpoint. Acceptance is displayed as accepted, delivery unknown.

Meta's official examples and API collection describe templates and webhook-based status updates:

- [Meta WhatsApp API examples](https://github.com/fbsamples/whatsapp-api-examples)
- [Meta WhatsApp Cloud API collection](https://www.postman.com/meta/whatsapp-business-platform/documentation/wlk6lh4/whatsapp-cloud-api)
- [Meta webhook payload reference](https://www.postman.com/meta/whatsapp-business-platform/folder/tduohwq/webhook-payload-reference)

Automatic inbound messages and delivered/read updates would require a separate, authenticated callback receiver or a genuinely supported provider retrieval service. This outbound-only desktop release does not deploy that infrastructure. Staff record customer decisions and vendor updates in the native interface.

## Email

Configure the provider's authenticated SMTP host, STARTTLS port (normally 587), username and sender address. TLS certificate validation is enabled. Authentication supports XOAUTH2 using an owner-supplied access token, or an application-specific password **only if the provider supports it**. A normal mailbox password is not assumed to work. Refresh/re-enter expiring OAuth tokens through the provider's authorized process; this desktop release does not register an OAuth client or implement a provider-specific refresh-token flow.

Microsoft documents SMTP AUTH with OAuth and the SASL XOAUTH2 protocol:

- [Enable or disable SMTP AUTH](https://learn.microsoft.com/en-us/exchange/clients-and-mobile-in-exchange-online/authenticated-client-smtp-submission)
- [OAuth authentication for IMAP, POP and SMTP](https://learn.microsoft.com/en-us/exchange/client-developer/legacy-protocols/how-to-authenticate-an-imap-pop-smtp-application-by-using-oauth)

SMTP acceptance is not delivery. No bounce ingestion or read-receipt claim is made.

## Outbox operations

Events include intake, issued quote, recorded decision, revised dates, dispatch, centre decisions, external completion/awaiting return, shop arrival, repaired/unrepaired readiness and collection. Records persist their recipient, channel, body/template snapshot, business/version reference, state, attempts, timestamps, provider ID and error. Equal normalized destinations for the same event are deduplicated across owner/submitter roles.

Each worker claims before sending. Safe connection/rate-limit failures retry at bounded exponential intervals, up to five submissions. An ambiguous timeout, server error or interrupted submission becomes uncertain and is not automatically retried. Revalidate current consent, address, quote version and pickup stage before sending. Cancel stale rows. An uncertain row can be cancelled after reviewing the provider console; a new business notification should be created only when the operator knows it is appropriate.

Windows Credential Manager holds `whatsapp_token` and `smtp_credential` under the `RepairShop Manager` service. No secret is written to ordinary settings, exports, PDFs or archives. On another computer, the owner must re-enter credentials. Restored history is paused for reconciliation; changing mode to live does not itself convert restored rows back to pending.

Configure staff/vendor recipients separately from customer records. Opted-in owners and assigned technicians can receive job updates; vendor recipients are used for deliberately reviewed email statements. **Send saved statement PDF** previews the actual saved document, recipient, subject and body before queueing it. It uses email attachments; WhatsApp document uploads are not implemented. Body and subject templates accept only listed variables and cannot pull internal costs automatically.

Collection reminders are disabled by default. Set an interval of 1–90 days to enable them, with a maximum of three reminder events per job. They apply only to overdue collection dates, recheck that the device remains at the shop, and stop after collection or a changed readiness state.

Live-provider connectivity, account credentials, approved template behavior and actual customer delivery require owner-side configuration and have not been tested against a real account.
