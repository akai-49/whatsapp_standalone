"""Sync messages sent from the WhatsApp Business mobile app into `WhatsApp Message`.

In Coexistence mode Meta reports each message typed in the Business app as an
`smb_message_echoes` webhook. `frappe_whatsapp` logs that webhook but does not process it.
"""

import json
from datetime import UTC, datetime

import frappe

ECHO_FIELD = "smb_message_echoes"
WEBHOOK_LOG_TEMPLATE = "Webhook"
ECHO_STATUS = "sent"
SAVE_POINT = "whatsapp_echo"


def sync_message_echoes(doc, method=None):
	"""Save the Business-app echoes in a webhook log as outgoing WhatsApp messages.

	`after_insert` hook of `WhatsApp Notification Log`.

	Args:
		doc: the `WhatsApp Notification Log` that holds the raw webhook in `meta_data`.
		method: the doc event name; not used.

	Side effects: inserts `WhatsApp Message` documents. Never raises: a failure is rolled
	back to a savepoint and written to the Error Log, so the webhook itself still succeeds.
	"""
	if doc.template != WEBHOOK_LOG_TEMPLATE:
		return
	for echo, phone_id in _get_echoes(doc.meta_data):
		frappe.db.savepoint(SAVE_POINT)
		try:
			_save_echo(echo, phone_id)
		except Exception:
			frappe.db.rollback(save_point=SAVE_POINT)
			frappe.log_error(title="WhatsApp echo sync failed", message=frappe.get_traceback())


def _get_echoes(meta_data):
	"""Return `(echo, phone_number_id)` pairs from a raw webhook payload; empty if it has none."""
	try:
		payload = json.loads(meta_data)
		changes = [change for entry in payload["entry"] for change in entry["changes"]]
	except (TypeError, ValueError, KeyError):
		return []
	return [
		(echo, change["value"].get("metadata", {}).get("phone_number_id"))
		for change in changes
		if change.get("field") == ECHO_FIELD
		for echo in change.get("value", {}).get("message_echoes", [])
	]


def _save_echo(echo, phone_id):
	"""Insert one echo as an outgoing message, unless it is unsupported or already saved.

	Side effects: one `WhatsApp Message` insert; CRM's hooks link it to the lead or deal.
	"""
	values = _get_message_values(echo)
	if not values or frappe.db.exists("WhatsApp Message", {"message_id": values["message_id"]}):
		return
	account = phone_id and frappe.db.get_value("WhatsApp Account", {"phone_id": phone_id}, "name")
	if account:
		values["whatsapp_account"] = account

	message = frappe.get_doc(values)
	# The message is already delivered. Without this, frappe_whatsapp sends every new
	# outgoing message to Meta and the customer would get it twice.
	message.send_outgoing = lambda: None
	message.insert(ignore_permissions=True)
	if echo.get("timestamp"):
		sent_at = datetime.fromtimestamp(int(echo["timestamp"]), UTC).replace(tzinfo=None)
		local_sent_at = frappe.utils.convert_utc_to_system_timezone(sent_at).replace(tzinfo=None)
		message.db_set("creation", local_sent_at, update_modified=False)


def _get_message_values(echo):
	"""Map an echo to `WhatsApp Message` field values, or None if it cannot be saved."""
	# ponytail: text and reactions only; media echoes need a download step from the Graph API.
	if echo.get("type") == "text":
		content = {"message": echo.get("text", {}).get("body"), "content_type": "text"}
	elif echo.get("type") == "reaction":
		reaction = echo.get("reaction", {})
		content = {
			"message": reaction.get("emoji"),
			"content_type": "reaction",
			"reply_to_message_id": reaction.get("message_id"),
		}
	else:
		return None
	if not (echo.get("id") and echo.get("to") and content["message"]):
		return None
	return {
		"doctype": "WhatsApp Message",
		"type": "Outgoing",
		"to": echo["to"],
		"message_id": echo["id"],
		"status": ECHO_STATUS,
		**content,
	}
