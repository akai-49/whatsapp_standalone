"""Create a CRM Lead from the first incoming WhatsApp message of an unknown number.

`frappe_whatsapp` saves every incoming message as a `WhatsApp Message`. This module turns the
first message from a number that is not yet a lead or a deal into a `CRM Lead`.
"""

import frappe
from redis.exceptions import RedisError

CRM_APP = "crm"
INCOMING_TYPE = "Incoming"
LEAD_DOCTYPE = "CRM Lead"
DEAL_DOCTYPE = "CRM Deal"
LEAD_SOURCE = "WhatsApp"
LEAD_STATUS = "New"
LEAD_NAME_MAX_LENGTH = 140  # length limit of a Data field
SAVE_POINT = "whatsapp_incoming_lead"
LOCK_KEY_PREFIX = "whatsapp_incoming_lead"
LOCK_TIMEOUT_SECONDS = 30
LOCK_WAIT_SECONDS = 2
ERROR_TITLE = "WhatsApp lead create failed"
LOCK_ERROR_TITLE = "WhatsApp lead create skipped: number is locked"
# `mobile_no` and `phone` are stored in mixed formats ("+91 90195 32735", "+91-98765-43210").
NUMBER_COLUMNS = ("mobile_no", "phone")
NUMBER_SEPARATORS = (" ", "+", "-", "(", ")", ".")


def create_lead_for_incoming_message(doc, method=None):
	"""Create a CRM Lead for an incoming message from a number that is not a lead or deal yet.

	`after_insert` hook of `WhatsApp Message`.

	Args:
		doc: the saved `WhatsApp Message`.
		method: the doc event name; not used.

	Side effects: may insert one `CRM Lead`, takes a short Redis lock per number, and writes to
	the Error Log on failure. Never raises, so the webhook still returns 200 and Meta does not
	retry. Does not commit; the request transaction does. Does nothing when CRM is not installed.
	"""
	if doc.type != INCOMING_TYPE:
		return
	digits = _normalise_number(doc.get("from"))
	if not digits or CRM_APP not in frappe.get_installed_apps():
		return

	frappe.db.savepoint(SAVE_POINT)
	try:
		_create_lead_under_lock(doc, digits)
	except Exception:
		frappe.db.rollback(save_point=SAVE_POINT)
		frappe.log_error(title=ERROR_TITLE, message=frappe.get_traceback())


def _create_lead_under_lock(doc, digits):
	"""Check for an existing record and insert the lead while holding the number's lock.

	The lock makes the check and the insert one step, so two messages from a new number that
	arrive together cannot create two leads. It is released only when the request transaction
	ends: until then the new lead is invisible to other requests, and a message that took the
	lock earlier would not see it and would create a duplicate.

	Raises: any error from the database or Redis; the caller logs it and rolls back.
	"""
	lock = frappe.cache.lock(
		_get_lock_name(digits), timeout=LOCK_TIMEOUT_SECONDS, blocking_timeout=LOCK_WAIT_SECONDS
	)
	if not lock.acquire():
		frappe.log_error(title=LOCK_ERROR_TITLE, message=f"WhatsApp Message {doc.name}")
		return
	frappe.db.after_commit.add(lambda: _release_lock(lock))
	frappe.db.after_rollback.add(lambda: _release_lock(lock))

	if not _record_exists(digits):
		frappe.get_doc(_build_lead_values(doc, digits)).insert(ignore_permissions=True)


def _normalise_number(sender):
	"""Return only the digits of a sender number, or an empty string if there are none."""
	if not isinstance(sender, str):
		return ""
	return "".join(char for char in sender if char.isdigit())


def _get_lock_name(digits):
	"""Return the Redis lock name; it holds the site so sites on one bench never share a lock."""
	return f"{LOCK_KEY_PREFIX}:{frappe.local.site}:{digits}"


def _digits_only_sql(column):
	"""Return a SQL expression that strips the number separators from `column`."""
	expression = column
	for separator in NUMBER_SEPARATORS:
		expression = f"replace({expression}, '{separator}', '')"
	return expression


def _record_exists(digits):
	"""Return True if a CRM Lead or CRM Deal already has this number in `mobile_no` or `phone`."""
	# ponytail: exact match on the full digit string; a number saved without its country code
	# is not matched. Add a suffix match if that causes duplicate leads. replace() also defeats
	# any index on the number columns, so this scans both tables; store a digits-only column if
	# they grow to hundreds of thousands of rows.
	conditions = " or ".join(f"{_digits_only_sql(column)} = %s" for column in NUMBER_COLUMNS)
	return any(
		frappe.db.sql(
			f"select name from `tab{doctype}` where {conditions} limit 1",
			(digits,) * len(NUMBER_COLUMNS),
		)
		for doctype in (LEAD_DOCTYPE, DEAL_DOCTYPE)
	)


def _build_lead_values(doc, digits):
	"""Return the `CRM Lead` field values for an incoming message."""
	return {
		"doctype": LEAD_DOCTYPE,
		"first_name": _get_first_name(doc.get("profile_name")) or digits,
		"mobile_no": f"+{digits}",
		"source": LEAD_SOURCE,
		"status": LEAD_STATUS,
	}


def _get_first_name(profile_name):
	"""Return the WhatsApp profile name as a plain name that fits a Data field, or ''."""
	if not isinstance(profile_name, str):
		return ""
	return frappe.utils.strip_html(profile_name).strip()[:LEAD_NAME_MAX_LENGTH]


def _release_lock(lock):
	"""Release the lock after the transaction ended; Redis trouble must not surface here.

	An expired lock or an unreachable Redis is fine: the lock has a timeout, and the lead work
	is already committed or rolled back.
	"""
	try:
		lock.release()
	except RedisError:
		pass
