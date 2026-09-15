"""Outbound-only adapters. Provider acceptance never means delivered/read."""
import base64
from datetime import datetime, timezone, timedelta, date
from email.message import EmailMessage
from pathlib import Path
import json
import smtplib
import ssl
import uuid
import httpx
import keyring
from .domain import now, RuleError, today, sql_in_shop


#: What each stored outbox state means to the person reading the screen. A message that
#: was refused for missing consent is never described as queued or sent.
STATUS_LABELS = {
    'pending': 'Queued',
    'sending': 'Sending',
    'retryable': 'Retrying after a temporary failure',
    'accepted': 'Sent',
    'captured': 'Sent (test mode)',
    'blocked_consent': 'Blocked — consent missing',
    'blocked_configuration': 'Blocked — messaging not configured',
    'permanent_failure': 'Failed',
    'uncertain': 'Unconfirmed — check before resending',
    'cancelled': 'Cancelled',
    'channel_disabled': 'Held — channel switched off in Settings',
    'no_contact': 'Skipped — no contact information',
}


def status_label(state):
    return STATUS_LABELS.get(state, str(state).replace('_', ' ').title())


class Uncertain(Exception):
    pass


class Permanent(Exception):
    pass


class Retryable(Exception):
    pass


def secret(name, value=None):
    if value is not None:
        keyring.set_password("RepairShop Manager", name, value)
    return keyring.get_password("RepairShop Manager", name)


class WhatsApp:
    def __init__(self, config):
        self.config = config

    def _upload(self, token, path, filename):
        """Upload the PDF to the Cloud API media store and return its media id.

        Uploading delivers nothing to the customer, so a lost connection here is always
        safe to retry: only the message send itself can leave an uncertain outcome.
        """
        cfg = self.config
        try:
            with open(path, "rb") as handle:
                response = httpx.post(
                    f"https://graph.facebook.com/{cfg['api_version']}/{cfg['phone_number_id']}/media",
                    headers={"Authorization": "Bearer " + token},
                    data={"messaging_product": "whatsapp"},
                    files={"file": (filename, handle, "application/pdf")}, timeout=60)
        except OSError:
            raise Permanent("The document to attach could not be read from disk.")
        except httpx.ConnectError:
            raise Retryable("Could not connect to provider to upload the document.")
        except (httpx.TimeoutException, httpx.NetworkError):
            raise Retryable("Document upload did not complete; nothing was sent yet.")
        if response.status_code == 429:
            raise Retryable("Provider rate limit while uploading the document; retry later.")
        if response.status_code >= 500:
            raise Retryable("Provider server error while uploading the document; nothing was sent yet.")
        if response.status_code >= 400:
            raise Permanent(f"WhatsApp rejected the document upload (HTTP {response.status_code}). Check the file type and account settings.")
        try:
            return response.json()["id"]
        except (KeyError, ValueError):
            raise Retryable("Provider did not return a document reference; nothing was sent yet.")

    def send(self, row, payload):
        cfg = self.config
        token = secret("whatsapp_token")
        template = payload.get("template", {})
        if not token or not cfg.get("phone_number_id") or not cfg.get("api_version") or not template.get("name"):
            raise RuleError("Configure WhatsApp credentials, API version and approved event template.")
        data = {"messaging_product": "whatsapp", "to": row["destination"].lstrip("+"), "type": "template", "template": {"name": template["name"], "language": {"code": template.get("language", "en")}}}
        # This deployment uses a preapproved template with a single body variable. When a
        # document is attached the same template carries it in an approved document
        # header, so the customer receives the PDF the message refers to.
        components = []
        if payload.get("_attachment_path"):
            filename = payload.get("_attachment_name") or "document.pdf"
            media = self._upload(token, payload["_attachment_path"], filename)
            components.append({"type": "header", "parameters": [
                {"type": "document", "document": {"id": media, "filename": filename}}]})
        components.append({"type": "body", "parameters": [{"type": "text", "text": payload["body"]}]})
        data["template"]["components"] = components
        try:
            response = httpx.post(f"https://graph.facebook.com/{cfg['api_version']}/{cfg['phone_number_id']}/messages", headers={"Authorization": "Bearer " + token}, json=data, timeout=25)
        except httpx.ConnectError:
            raise Retryable("Could not connect to provider.")
        except (httpx.TimeoutException, httpx.NetworkError):
            raise Uncertain("Connection ended without a confirmed outcome; do not blindly resend.")
        if response.status_code == 429:
            raise Retryable("Provider rate limit; retry later.")
        if response.status_code >= 500:
            raise Uncertain("Provider server error; acceptance could not be confirmed.")
        if response.status_code >= 400:
            detail = " The template also needs an approved document header to carry an attachment." if payload.get("_attachment_path") else ""
            raise Permanent(f"WhatsApp rejected the request (HTTP {response.status_code}). Check account/template settings." + detail)
        try:
            return response.json()["messages"][0]["id"]
        except (KeyError, ValueError, IndexError):
            raise Uncertain("Unexpected provider response; review before retrying.")


class SMTP:
    def __init__(self, config):
        self.config = config

    def send(self, row, payload):
        cfg = self.config
        credential = secret("smtp_credential")
        if not cfg.get("host") or not cfg.get("username") or not credential:
            raise RuleError("Configure email server and authentication first.")
        msg = EmailMessage()
        msg["From"] = cfg.get("from_address") or cfg["username"]
        msg["To"] = row["destination"]
        msg["Subject"] = payload["subject"]
        msg["Message-ID"] = f"<repairshop-{row['id']}-{row['event_key']}@local.invalid>"
        msg.set_content(payload["body"])
        if payload.get('_attachment_path'):
            path=Path(payload['_attachment_path'])
            msg.add_attachment(path.read_bytes(),maintype='application',subtype='pdf',filename=payload.get('_attachment_name','statement.pdf'))
        submitted = False
        try:
            context = ssl.create_default_context()
            with smtplib.SMTP(cfg["host"], int(cfg.get("port", 587)), timeout=25) as smtp:
                smtp.ehlo()
                smtp.starttls(context=context)
                smtp.ehlo()
                if cfg.get("auth", "oauth2") == "oauth2":
                    auth = base64.b64encode(f"user={cfg['username']}\x01auth=Bearer {credential}\x01\x01".encode()).decode()
                    code, _ = smtp.docmd("AUTH", "XOAUTH2 " + auth)
                    if code != 235:
                        raise Permanent("OAuth authentication rejected; refresh the access token in settings.")
                elif cfg.get("auth") == "app_password":
                    smtp.login(cfg["username"], credential)
                else:
                    raise RuleError("Select OAuth2 or a provider-supported app password.")
                submitted = True
                rejected = smtp.send_message(msg)
                if rejected:
                    raise Permanent("Email recipient was rejected.")
        except (smtplib.SMTPAuthenticationError, smtplib.SMTPRecipientsRefused):
            raise Permanent("Email authentication or recipient rejected.")
        except (OSError, smtplib.SMTPException):
            if submitted:
                raise Uncertain("SMTP submission outcome is unknown; review before retrying.")
            raise Retryable("Could not establish an authenticated TLS mail connection.")
        return str(msg["Message-ID"])


class Outbox:
    def __init__(self, service, adapters=None):
        self.s, self.db = service, service.db
        self.adapters = adapters

    def recover_claims(self):
        if self.db.readonly:
            return
        with self.db.transaction() as c:
            c.execute("UPDATE outbox SET state='uncertain',error='Previous process stopped during submission; review before retrying',updated=? WHERE state='sending'", (now(),))

    def _valid(self, c, row):
        # The shop may have switched the channel off after this was queued. Hold the
        # message with a clear reason rather than sending it or discarding it; it can be
        # retried once the channel is switched back on.
        if not self.s.channel_enabled(row['channel']):
            return 'channel_disabled', row['channel'].title() + ' sending is switched off in Settings.'
        if row['contact_id']:
            customer = c.execute("SELECT * FROM customers WHERE id=?", (row["contact_id"],)).fetchone()
            if not customer or not customer[row["channel"] + "_consent"]:
                return "blocked_consent", "Current contact consent is missing."
            destination = customer["phone" if row["channel"] == "whatsapp" else "email"]
        else:
            recipient=c.execute('SELECT * FROM recipients WHERE id=?',(row['recipient_id'],)).fetchone()
            if not recipient or not recipient['active'] or not recipient['consent']:
                return 'blocked_consent','Configured recipient is inactive or has not consented.'
            destination=recipient['destination']
        if destination != row["destination"]:
            return "cancelled", "Contact destination changed; create a new reviewed notification."
        if row["quote_id"]:
            q = c.execute("SELECT * FROM quotes WHERE id=?", (row["quote_id"],)).fetchone()
            if not q or q["state"] == "superseded" or (q["valid_until"] and q["valid_until"] < today()):
                return "cancelled", "Quotation obsolete or expired."
            if row['event'] == 'quote_issued' and q['state'] != 'issued':
                return 'cancelled', 'The customer decision has already been recorded.'
        if row["job_id"]:
            j = c.execute("SELECT * FROM jobs WHERE id=?", (row["job_id"],)).fetchone()
            if row["event"] in ("ready_repaired", "ready_unrepaired", "awaiting_return") and j["stage"] != row["event"]:
                return "cancelled", "Job stage changed; notification is obsolete."
            if row['event'] == 'collection_reminder' and j['stage'] not in ('ready_repaired','ready_unrepaired'):
                return 'cancelled','Collection reminder is no longer relevant.'
            if row['event'] in ('ready_repaired','ready_unrepaired','collection_reminder'):
                at_shop = c.execute("SELECT sum(h.quantity) FROM holdings h JOIN items i ON i.id=h.item_id WHERE i.job_id=? AND i.type='device' AND "+sql_in_shop('h.location')+"", (j['id'],)).fetchone()[0]
                if not at_shop:
                    return 'cancelled', 'The device is no longer at the shop for collection.'
            if row["event"] == "dates_revised" and json.loads(row["payload"])["job_version"] != j["version"]:
                return "cancelled", "Job changed after the date notification was prepared."
        return None

    def process_one(self):
        if self.db.readonly or self.db.setting("notifications_paused", False):
            return False
        with self.db.transaction() as c:
            row = c.execute("SELECT * FROM outbox WHERE state IN ('pending','retryable') AND (next_attempt IS NULL OR next_attempt<=?) ORDER BY id LIMIT 1", (now(),)).fetchone()
            if not row:
                return False
            row = dict(row)
            invalid = self._valid(c, row)
            if invalid:
                c.execute("UPDATE outbox SET state=?,error=?,updated=? WHERE id=?", (*invalid, now(), row["id"]))
                return True
            if c.execute("UPDATE outbox SET state='sending',attempts=attempts+1,updated=? WHERE id=? AND state IN ('pending','retryable')", (now(), row["id"])).rowcount != 1:
                return True
        state, error, provider_id, retry = "accepted", "", None, None
        try:
            payload = json.loads(row['payload'])
            if row.get('attachment_id'):
                attachment=self.db.one('SELECT * FROM attachments WHERE id=?',(row['attachment_id'],))
                from .local_files import managed_path
                path=managed_path(self.db.root, attachment['path']) if attachment else None
                if not path or not path.is_file():
                    raise RuleError('The selected issued attachment is unavailable.')
                payload['_attachment_path']=str(path)
                payload['_attachment_name']=path.name
            if self.db.setting("messaging_mode", "test") == "test" and self.adapters is None:
                state, provider_id = "captured", "local-test-" + uuid.uuid4().hex
            else:
                adapters = self.adapters or {"whatsapp": WhatsApp(self.db.setting("whatsapp", {})), "email": SMTP(self.db.setting("smtp", {}))}
                provider_id = adapters[row["channel"]].send(row, payload)
        except RuleError as exc:
            state, error = "blocked_configuration", str(exc)
        except Permanent as exc:
            state, error = "permanent_failure", str(exc)
        except Uncertain as exc:
            state, error = "uncertain", str(exc)
        except Retryable as exc:
            state, error = ("retryable" if row["attempts"] < 4 else "permanent_failure"), str(exc)
            retry = (datetime.now(timezone.utc) + timedelta(seconds=min(3600, 60 * 2**row["attempts"]))).isoformat(timespec="seconds")
        except Exception:
            state, error = "uncertain", "Unexpected adapter failure; review outcome before retrying."
        with self.db.transaction() as c:
            c.execute("UPDATE outbox SET state=?,error=?,provider_id=?,next_attempt=?,updated=? WHERE id=?", (state, error, provider_id, retry, now(), row["id"]))
        return True

    def schedule_reminders(self):
        if self.db.readonly or self.db.setting('notifications_paused',False):
            return
        interval=int(self.db.setting('reminder_days',0))
        if interval<=0:
            return
        # Whether a collection is overdue is an Indian business day, not a UTC one:
        # before 05:30 IST the UTC date is still yesterday.
        today_local=date.fromisoformat(today())
        with self.db.transaction() as c:
            jobs=c.execute("SELECT * FROM jobs WHERE stage IN ('ready_repaired','ready_unrepaired') AND collection_due IS NOT NULL AND collection_due<? LIMIT 500",(today_local.isoformat(),)).fetchall()
            for j in jobs:
                previous=c.execute("SELECT count(DISTINCT event_key),max(created) FROM outbox WHERE job_id=? AND event='collection_reminder'",(j['id'],)).fetchone()
                if previous[0]>=3 or (previous[1] and datetime.fromisoformat(previous[1]).date()+timedelta(days=interval)>today_local):
                    continue
                qualifier='without repair' if j['stage']=='ready_unrepaired' else 'after repair and testing'
                self.s.notify(c,j['id'],'collection_reminder',f"Your device remains ready for collection {qualifier}. Please contact the shop to arrange pickup.",event_key=f"reminder-{j['id']}-{today_local}")

    def action(self, ident, action):
        self.s.require_permission('messaging')
        with self.db.transaction() as c:
            row = c.execute("SELECT * FROM outbox WHERE id=?", (ident,)).fetchone()
            if not row:
                raise RuleError("Notification not found.")
            if action == "retry" and row["state"] not in ("retryable", "blocked_consent", "blocked_configuration", "channel_disabled", "permanent_failure"):
                raise RuleError("Only confirmed failures or blocked messages may be retried. Uncertain/restored messages require reconciliation.")
            if row["state"] == "sending":
                raise RuleError("Wait for the in-flight submission to finish.")
            state = "pending" if action == "retry" else "cancelled"
            c.execute("UPDATE outbox SET state=?,next_attempt=NULL,error='',updated=? WHERE id=?", (state, now(), ident))
            self.s.audit(c, "message", ident, action, {"previous": row["state"]})
