"""Show WhatsApp messages in the Activity timeline of a CRM Lead or Deal.

The Activity tab of Frappe CRM draws only versions, comments, calls and `Communication` records;
WhatsApp messages have a tab of their own. This module saves one `Communication` per message,
which the tab draws as a card. The WhatsApp tab keeps the full chat.
"""

import frappe

TIMELINE_DOCTYPES = ("CRM Lead", "CRM Deal")
COMMUNICATION_DOCTYPE = "Communication"
COMMUNICATION_TYPE = "Communication"
COMMUNICATION_MEDIUM = "Chat"
INCOMING_TYPE = "Incoming"
RECEIVED = "Received"
SENT = "Sent"
MESSAGE_ID_PREFIX = "whatsapp:"
SUBJECT_FROM = "WhatsApp message from"
SUBJECT_TO = "WhatsApp message to"
OUTGOING_SENDER_NAME = "WhatsApp"
EMPTY_BODY_LABEL_FALLBACK = "message"
SAVE_POINT = "whatsapp_timeline_entry"
ERROR_TITLE = "WhatsApp timeline entry failed"


def mirror_message_to_timeline(doc, method=None):
	"""Save a `Communication` for a WhatsApp message that belongs to a lead or deal.

	`after_insert` hook of `WhatsApp Message`; it runs after the handler that creates the lead,
	so the first message of a new number is linked by then.

	Args:
		doc: the saved `WhatsApp Message`.
		method: the doc event name; not used.

	Side effects: may insert one `Communication` and write to the Error Log on failure. A message
	that already has an entry (a Meta retry) gets no second one. Never raises, so the webhook
	still returns 200. Does not commit; the request transaction does.
	"""
	if doc.get("reference_doctype") not in TIMELINE_DOCTYPES or not doc.get("reference_name"):
		return

	frappe.db.savepoint(SAVE_POINT)
	try:
		message_id = f"{MESSAGE_ID_PREFIX}{doc.name}"
		if not frappe.db.exists(COMMUNICATION_DOCTYPE, {"message_id": message_id}):
			frappe.get_doc(_build_communication_values(doc, message_id)).insert(ignore_permissions=True)
	except Exception:
		frappe.db.rollback(save_point=SAVE_POINT)
		frappe.log_error(title=ERROR_TITLE, message=frappe.get_traceback())


def _build_communication_values(doc, message_id):
	"""Return the `Communication` field values for a WhatsApp message.

	The number goes in the subject and the sender name, not in `sender` or `recipients`:
	Communication checks those as email addresses.
	"""
	is_incoming = doc.type == INCOMING_TYPE
	number = f"+{doc.get('from') if is_incoming else doc.get('to')}"
	sender_name = (doc.get("profile_name") or "").strip() or number
	return {
		"doctype": COMMUNICATION_DOCTYPE,
		"communication_type": COMMUNICATION_TYPE,
		"communication_medium": COMMUNICATION_MEDIUM,
		"sent_or_received": RECEIVED if is_incoming else SENT,
		"subject": f"{SUBJECT_FROM if is_incoming else SUBJECT_TO} {number}",
		"content": _get_content(doc),
		"sender_full_name": sender_name if is_incoming else OUTGOING_SENDER_NAME,
		"communication_date": doc.get("creation"),
		"message_id": message_id,
		"reference_doctype": doc.get("reference_doctype"),
		"reference_name": doc.get("reference_name"),
	}


def _get_content(doc):
	"""Return the message text as safe HTML, or the content type in brackets when there is no text."""
	body = (doc.get("message") or "").strip()
	if not body:
		return f"[{doc.get('content_type') or EMPTY_BODY_LABEL_FALLBACK}]"
	return frappe.utils.escape_html(body)
