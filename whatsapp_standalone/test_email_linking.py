"""Tests for linking shared-mailbox emails to a lead. `frappe` is mocked; no site or database is used."""

import unittest
from unittest.mock import patch

from whatsapp_standalone.email_linking import link_email_to_lead

ERROR_TITLE = "Email lead link failed"


class FakeCommunication:
	"""Stand-in `Communication`; `get` reads a field the way a `Document` does."""

	def __init__(self, **values):
		self.__dict__.update(values)

	def get(self, key, default=None):
		return self.__dict__.get(key, default)


def make_email(**extra):
	values = {
		"communication_medium": "Email",
		"sent_or_received": "Received",
		"email_account": "Shared Inbox",
		"sender": "asha@example.com",
		"recipients": "team@example.com",
		"cc": "",
		"reference_doctype": None,
		"reference_name": None,
	}
	return FakeCommunication(**{**values, **extra})


class TestLinkEmailToLead(unittest.TestCase):
	def setUp(self):
		patcher = patch("whatsapp_standalone.email_linking.frappe")
		self.frappe = patcher.start()
		self.addCleanup(patcher.stop)

		self.frappe.get_traceback.return_value = "traceback"
		self.frappe.db.get_all.return_value = ["CRM-LEAD-1"]

	def assert_not_looked_up(self):
		self.frappe.db.get_all.assert_not_called()

	# --- emails that are left alone ----------------------------------------------------

	def test_only_unlinked_emails_of_a_mail_account_are_handled(self):
		for extra in (
			{"communication_medium": "Chat"},
			{"communication_medium": None},
			{"communication_medium": ""},
			{"email_account": None},
			{"email_account": ""},
			{"reference_doctype": "CRM Lead", "reference_name": "CRM-LEAD-9"},
			{"reference_doctype": "CRM Deal", "reference_name": "CRM-DEAL-9"},
			{"reference_doctype": "Issue", "reference_name": "ISS-1"},
		):
			with self.subTest(extra=extra):
				email = make_email(**extra)
				link_email_to_lead(email)
				self.assert_not_looked_up()

	def test_addresses_that_are_not_emails_are_not_looked_up(self):
		for sender in (None, "", "   ", "no at sign", "<>", 42):
			with self.subTest(sender=sender):
				link_email_to_lead(make_email(sender=sender))
				self.assert_not_looked_up()

	# --- which address is matched -------------------------------------------------------

	def test_received_email_is_matched_by_its_sender(self):
		email = make_email(recipients="team@example.com, other@example.com")

		link_email_to_lead(email)

		self.frappe.db.get_all.assert_called_once_with(
			"CRM Lead", filters={"email": ["in", ["asha@example.com"]]}, pluck="name", limit=2
		)
		self.assertEqual((email.reference_doctype, email.reference_name), ("CRM Lead", "CRM-LEAD-1"))

	def test_sent_email_is_matched_by_recipients_and_cc(self):
		email = make_email(
			sent_or_received="Sent",
			sender="team@example.com",
			recipients="Asha <asha@example.com>, bo@example.com",
			cc="bo@example.com\nCy@Example.com",
		)

		link_email_to_lead(email)

		filters = self.frappe.db.get_all.call_args.kwargs["filters"]
		self.assertEqual(filters, {"email": ["in", ["asha@example.com", "bo@example.com", "cy@example.com"]]})

	def test_display_name_and_case_are_ignored(self):
		link_email_to_lead(make_email(sender='"Asha B" <Asha.B@Example.COM>'))

		filters = self.frappe.db.get_all.call_args.kwargs["filters"]
		self.assertEqual(filters, {"email": ["in", ["asha.b@example.com"]]})

	def test_injection_text_stays_a_filter_value(self):
		payload = "x'; DROP TABLE `tabCRM Lead`;--@example.com"
		link_email_to_lead(make_email(sender=payload))

		for call in self.frappe.db.get_all.call_args_list:
			self.assertEqual(call.args, ("CRM Lead",))
			self.assertEqual(set(call.kwargs), {"filters", "pluck", "limit"})

	# --- how many leads match -------------------------------------------------------------

	def test_the_email_is_linked_only_when_exactly_one_lead_matches(self):
		for leads, linked in (([], False), (["CRM-LEAD-1"], True), (["CRM-LEAD-1", "CRM-LEAD-2"], False)):
			with self.subTest(leads=leads):
				self.frappe.db.get_all.return_value = leads
				email = make_email()

				link_email_to_lead(email)

				self.assertEqual(bool(email.reference_name), linked)
				if not linked:
					self.assertIsNone(email.reference_doctype)

	# --- failures --------------------------------------------------------------------------

	def test_database_error_is_logged_and_never_raised(self):
		self.frappe.db.get_all.side_effect = RuntimeError("db down")
		email = make_email()

		link_email_to_lead(email)

		self.frappe.log_error.assert_called_once_with(title=ERROR_TITLE, message="traceback")
		self.assertIsNone(email.reference_name)

	def test_handler_never_commits_or_rolls_back(self):
		link_email_to_lead(make_email())
		self.frappe.db.commit.assert_not_called()
		self.frappe.db.rollback.assert_not_called()


if __name__ == "__main__":
	unittest.main()
