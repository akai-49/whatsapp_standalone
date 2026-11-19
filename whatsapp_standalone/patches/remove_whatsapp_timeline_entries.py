import frappe

# What the removed `whatsapp_timeline` module wrote on every entry it made.
MESSAGE_ID_FILTER = ["like", "whatsapp:%"]
CHAT_MEDIUM = "Chat"


def execute():
	"""Delete the `Communication` entries that were made for WhatsApp messages.

	They showed in the Emails tab of a lead as email cards. Emails are never selected: an entry
	must have the `whatsapp:` message id and the Chat medium. The messages stay in the WhatsApp tab.

	Side effects: deletes `Communication` documents. Safe to run again.
	"""
	names = frappe.get_all(
		"Communication",
		filters={"message_id": MESSAGE_ID_FILTER, "communication_medium": CHAT_MEDIUM},
		pluck="name",
	)
	for name in names:
		frappe.delete_doc("Communication", name, force=True, ignore_permissions=True)
