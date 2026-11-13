import frappe

from whatsapp_standalone.echoes import ECHO_FIELD, WEBHOOK_LOG_TEMPLATE, sync_message_echoes


def execute():
	"""Save the Business-app echoes that were logged before this app handled them.

	Side effects: inserts `WhatsApp Message` documents. Echoes that are already saved are skipped.
	"""
	if not frappe.db.exists("DocType", "WhatsApp Notification Log"):
		return
	logs = frappe.get_all(
		"WhatsApp Notification Log",
		filters={"template": WEBHOOK_LOG_TEMPLATE, "meta_data": ("like", f"%{ECHO_FIELD}%")},
		fields=["name", "template", "meta_data"],
		order_by="creation asc",
	)
	for log in logs:
		sync_message_echoes(log)
