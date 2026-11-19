"""Show WhatsApp messages in the Activity timeline of a CRM Lead or Deal, but not in its Emails tab.

The Activity tab of Frappe CRM draws a plain text row for every entry whose type it does not
know, like "Kai created this lead". The Emails tab shows only entries of type `communication`.
This module wraps CRM's activities API and adds one such row per WhatsApp message, so the
messages appear in Activity and nowhere else. The WhatsApp tab keeps the full chat.

The row is an entry of type `creation`: the page draws `<owner> <data>` for it, wraps long text,
and does not cut it. The owner is shown through the page's user lookup; a name that is not a user
is shown as typed, up to a `@`.
"""

import frappe

CRM_ACTIVITIES_METHOD = "crm.api.activities.get_activities"
MESSAGE_DOCTYPE = "WhatsApp Message"
LEAD_DOCTYPE = "CRM Lead"
DEAL_DOCTYPE = "CRM Deal"
INCOMING_TYPE = "Incoming"
REACTION_TYPE = "reaction"
GUEST_USER = "Guest"
ROW_TYPE = "creation"
MESSAGE_LIMIT = 200
BODY_MAX_LENGTH = 300
ELLIPSIS = "…"
UNKNOWN_CONTACT = "WhatsApp contact"
UNKNOWN_ACCOUNT = "WhatsApp"
EMPTY_BODY_LABEL_FALLBACK = "message"
MESSAGE_FIELDS = (
	"name",
	"type",
	"from",
	"to",
	"profile_name",
	"message",
	"content_type",
	"creation",
	"owner",
	"whatsapp_account",
)
ACTIVITIES_RESULT_LENGTH = 5  # (activities, calls, notes, tasks, attachments)
ERROR_TITLE = "WhatsApp activity rows failed"


@frappe.whitelist()
def get_activities(name: str):
	"""Return CRM's activities of a lead or deal, with a row for each of its WhatsApp messages.

	Registered as the override of `crm.api.activities.get_activities`.

	Args:
		name: the name of a CRM Lead or CRM Deal.

	Returns: what CRM returns, `(activities, calls, notes, tasks, attachments)`, with the rows
	appended to `activities`. The page sorts them by `creation`.

	Raises: whatever CRM raises, such as a permission error. CRM runs first, so the permission
	check on the lead or deal is CRM's. An error while adding the rows is written to the Error Log
	and the CRM result is returned without them.

	Side effects: reads the database only.
	"""
	result = frappe.get_attr(CRM_ACTIVITIES_METHOD)(name)
	# Be defensive about the shape: this is another app's API and it can change on update.
	if (
		not isinstance(result, (list, tuple))
		or len(result) != ACTIVITIES_RESULT_LENGTH
		or not isinstance(result[0], list)
	):
		return result

	try:
		result[0].extend(_get_rows(name))
	except Exception:
		frappe.log_error(title=ERROR_TITLE, message=frappe.get_traceback())
	return result


def _get_rows(name):
	"""Return the timeline rows of the WhatsApp messages of a lead, or of a deal and its lead."""
	if not frappe.db.exists("DocType", MESSAGE_DOCTYPE):
		return []

	names = [name]
	if frappe.db.exists(DEAL_DOCTYPE, name):
		# CRM shows the messages of the lead a deal came from in the deal as well.
		lead = frappe.db.get_value(DEAL_DOCTYPE, name, "lead")
		if lead:
			names.append(lead)

	messages = frappe.get_all(
		MESSAGE_DOCTYPE,
		filters={"reference_doctype": ["in", [LEAD_DOCTYPE, DEAL_DOCTYPE]], "reference_name": ["in", names]},
		fields=list(MESSAGE_FIELDS),
		order_by="creation desc",
		limit=MESSAGE_LIMIT,
	)
	return [_build_row(message) for message in messages]


def _build_row(message):
	"""Return the Activity timeline entry for one `WhatsApp Message` row."""
	is_incoming = message.get("type") == INCOMING_TYPE
	number = _format_number(message.get("from") if is_incoming else message.get("to"))
	account = message.get("whatsapp_account") or ""
	if is_incoming:
		owner = _get_contact_name(message.get("profile_name"), number)
	else:
		owner = _get_sender_name(message.get("owner"), account)
	return {
		"name": message.get("name"),
		"activity_type": ROW_TYPE,
		"creation": message.get("creation"),
		"owner": owner,
		"data": _get_text(message, is_incoming, number, account),
		"is_lead": True,
	}


def _get_text(message, is_incoming, number, account):
	"""Return what the row says after the owner's name."""
	body = _get_body(message.get("message"))
	if message.get("content_type") == REACTION_TYPE:
		return f"reacted {body} to a WhatsApp message" if body else "removed a reaction from a WhatsApp message"

	if not body:
		body = f"[{message.get('content_type') or EMPTY_BODY_LABEL_FALLBACK}]"
	if is_incoming:
		return f"messaged {account} on WhatsApp: {body}" if account else f"messaged on WhatsApp: {body}"
	return f"sent a WhatsApp message to {number}: {body}"


def _get_body(text):
	"""Return a message text as plain text on one line, cut to `BODY_MAX_LENGTH` characters."""
	if not isinstance(text, str):
		return ""
	body = " ".join(frappe.utils.strip_html(text).split())
	if len(body) > BODY_MAX_LENGTH:
		body = body[: BODY_MAX_LENGTH - len(ELLIPSIS)] + ELLIPSIS
	return body


def _format_number(value):
	"""Return `+<digits>` for a WhatsApp number, or '' when it has no digits."""
	digits = "".join(char for char in value if char.isdigit()) if isinstance(value, str) else ""
	return f"+{digits}" if digits else ""


def _get_contact_name(profile_name, number):
	"""Return the name shown for a customer: profile name and number, whichever exist.

	The `@` is removed because the page treats an owner that is not a user as an email and shows
	only the part before it.
	"""
	name = _get_body(profile_name).replace("@", "")
	return " ".join(part for part in (name, number) if part) or UNKNOWN_CONTACT


def _get_sender_name(owner, account):
	"""Return the owner of an outgoing row: the CRM user, or the account for webhook-saved echoes."""
	if owner and owner != GUEST_USER:
		return owner
	return account or UNKNOWN_ACCOUNT
