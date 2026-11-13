"""Runtime fix for Frappe CRM's WhatsApp notification on version-16."""


def use_unchecked_assignee_lookup():
	"""Let the Guest WhatsApp webhook notify the assignees of a lead or deal.

	CRM's `notify_agent` calls the whitelisted `get_assigned_users`, which checks read
	permission on the reference document. The `frappe_whatsapp` webhook runs as Guest, so
	the check fails and the incoming message is rolled back. Upstream fixed this in
	frappe/crm#3214 by calling the internal `get_assignees`; this does the same from outside.

	Runs as a `before_request` hook. Side effect: rebinds `get_assigned_users` inside the
	`crm.api.whatsapp` module only. The whitelisted API in `crm.api.doc` is not changed.
	Does nothing when CRM is not installed or already has the fix.

	Remove this hook when the bench CRM includes frappe/crm#3214.
	"""
	try:
		import crm.api.whatsapp as crm_whatsapp
		from crm.api.doc import get_assignees
	except ImportError:
		return
	if hasattr(crm_whatsapp, "get_assigned_users"):
		crm_whatsapp.get_assigned_users = get_assignees
