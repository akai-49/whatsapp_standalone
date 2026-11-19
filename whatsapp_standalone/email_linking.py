"""Link emails of a shared mailbox to the CRM Lead of the person they belong to.

Frappe CRM links an email to a lead only when the reply carries the `#CRM-LEAD-…` tag in its
subject. Mail that comes into, or goes out of, a shared mailbox without that tag is unlinked, so
it is missing from the Activity timeline. This module links it by the email address instead.
"""

from email.utils import getaddresses

import frappe

LEAD_DOCTYPE = "CRM Lead"
EMAIL_MEDIUM = "Email"
RECEIVED = "Received"
ERROR_TITLE = "Email lead link failed"
# One more than the single match this module accepts, so that a second lead is noticed.
MATCH_LIMIT = 2


def link_email_to_lead(doc, method=None):
	"""Link an unlinked email to the one CRM Lead that has the address on the other end.

	`before_insert` hook of `Communication`. It runs before CRM's own `after_insert` handler, so
	CRM sees a linked email and does not make a second lead for it.

	Args:
		doc: the `Communication` about to be inserted.
		method: the doc event name; not used.

	The other end is the sender of a received email, and the recipients and cc of a sent one.
	Nothing is linked when no lead, or more than one lead, has such an address: a wrong link is
	worse than a missing one.

	Side effects: sets `reference_doctype` and `reference_name` on `doc`; writes to the Error Log
	on failure. Never raises, so mail fetching is not stopped. Reads only; does not commit.
	"""
	if (
		doc.get("communication_medium") != EMAIL_MEDIUM
		or not doc.get("email_account")
		or doc.get("reference_doctype")
		or doc.get("reference_name")
	):
		return

	try:
		leads = _find_leads(_get_other_end_addresses(doc))
	except Exception:
		frappe.log_error(title=ERROR_TITLE, message=frappe.get_traceback())
		return

	# ponytail: leads only; a deal's contact address is not matched. Add it if mail to a person
	# who is already a deal is missing from the deal's timeline.
	if len(leads) == 1:
		doc.reference_doctype = LEAD_DOCTYPE
		doc.reference_name = leads[0]


def _get_other_end_addresses(doc):
	"""Return the lower-case addresses of the person on the other end of the email, in order."""
	if doc.get("sent_or_received") == RECEIVED:
		texts = [doc.get("sender")]
	else:
		texts = [doc.get("recipients"), doc.get("cc")]

	addresses = []
	for text in texts:
		if not isinstance(text, str):
			continue
		for _name, address in getaddresses([text.replace("\n", ",")]):
			address = address.strip().lower()
			if "@" in address and address not in addresses:
				addresses.append(address)
	return addresses


def _find_leads(addresses):
	"""Return up to `MATCH_LIMIT` names of CRM Leads that have one of the addresses."""
	if not addresses:
		return []
	return frappe.db.get_all(
		LEAD_DOCTYPE, filters={"email": ["in", addresses]}, pluck="name", limit=MATCH_LIMIT
	)
