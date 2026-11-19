"""Tests for the WhatsApp rows of the CRM Activity timeline. `frappe` is mocked; no site or database is used."""

import re
import unittest
from unittest.mock import MagicMock, patch

from whatsapp_standalone.activity_timeline import get_activities

CRM_ACTIVITIES = "crm.api.activities.get_activities"
LEAD = "CRM-LEAD-1"
DEAL = "CRM-DEAL-1"
ACCOUNT = "walue.ai"
CREATED = "2026-11-19 10:00:00"
BODY_MAX_LENGTH = 300
MESSAGE_LIMIT = 200
ERROR_TITLE = "WhatsApp activity rows failed"


def make_message(**extra):
	values = {
		"name": "MSG-1",
		"type": "Incoming",
		"from": "919876543210",
		"to": None,
		"profile_name": "Asha",
		"message": "Hello",
		"content_type": "text",
		"creation": CREATED,
		"owner": "Guest",
		"whatsapp_account": ACCOUNT,
	}
	return {**values, **extra}


class TestGetActivities(unittest.TestCase):
	def setUp(self):
		patcher = patch("whatsapp_standalone.activity_timeline.frappe")
		self.frappe = patcher.start()
		self.addCleanup(patcher.stop)

		self.version = {"activity_type": "creation", "data": "created this lead"}
		self.crm_result = ([self.version], [], [], [], [])
		self.crm_get_activities = MagicMock(side_effect=lambda name: self.crm_result)
		self.frappe.get_attr.return_value = self.crm_get_activities
		self.frappe.get_traceback.return_value = "traceback"
		self.frappe.utils.strip_html.side_effect = lambda text: re.sub(r"<[^>]*>", "", text)
		self.frappe.db.exists.side_effect = lambda doctype, name=None: doctype == "DocType" or (
			doctype == "CRM Deal" and name == DEAL
		)
		self.frappe.db.get_value.return_value = LEAD
		self.messages = [make_message()]
		self.frappe.get_all.side_effect = lambda *args, **kwargs: self.messages

	def rows(self, name=LEAD):
		self.crm_result[0][:] = [self.version]  # the list is changed in place, so start from CRM's own
		return get_activities(name)[0][1:]

	# --- CRM's answer is kept ---------------------------------------------------------

	def test_the_crm_function_is_called_with_the_name_and_its_entries_are_kept(self):
		result = get_activities(LEAD)

		self.frappe.get_attr.assert_called_once_with(CRM_ACTIVITIES)
		self.crm_get_activities.assert_called_once_with(LEAD)
		self.assertIs(result, self.crm_result)
		self.assertIs(result[0][0], self.version)
		self.assertEqual(result[1:], ([], [], [], []))

	def test_result_is_unchanged_when_there_is_nothing_to_add(self):
		self.messages = []
		self.assertEqual(get_activities(LEAD)[0], [self.version])

		self.messages = [make_message()]
		self.frappe.db.exists.side_effect = lambda doctype, name=None: False  # no WhatsApp Message doctype
		self.assertEqual(get_activities(LEAD)[0], [self.version])

	def test_result_of_an_unexpected_shape_is_returned_as_it_is(self):
		for result in (None, {}, [], ([],), ([], [], [], []), ("x", [], [], [], [])):
			with self.subTest(result=result):
				self.crm_result = result
				self.assertIs(get_activities(LEAD), result)

	# --- which messages ----------------------------------------------------------------

	def test_lead_rows_come_from_the_messages_of_the_lead(self):
		get_activities(LEAD)

		args, kwargs = self.frappe.get_all.call_args
		self.assertEqual(args, ("WhatsApp Message",))
		self.assertEqual(
			kwargs["filters"],
			{"reference_doctype": ["in", ["CRM Lead", "CRM Deal"]], "reference_name": ["in", [LEAD]]},
		)
		self.assertEqual(kwargs["order_by"], "creation desc")
		self.assertEqual(kwargs["limit"], MESSAGE_LIMIT)
		for field in ("name", "type", "from", "to", "profile_name", "message", "content_type", "creation"):
			self.assertIn(field, kwargs["fields"])

	def test_deal_rows_also_come_from_the_messages_of_its_lead(self):
		get_activities(DEAL)

		filters = self.frappe.get_all.call_args.kwargs["filters"]
		self.assertEqual(filters["reference_name"], ["in", [DEAL, LEAD]])

	def test_deal_without_a_lead_uses_only_its_own_messages(self):
		self.frappe.db.get_value.return_value = None

		get_activities(DEAL)

		self.assertEqual(self.frappe.get_all.call_args.kwargs["filters"]["reference_name"], ["in", [DEAL]])

	# --- row values --------------------------------------------------------------------

	def test_incoming_text_row(self):
		self.assertEqual(
			self.rows(),
			[
				{
					"name": "MSG-1",
					"activity_type": "creation",
					"creation": CREATED,
					"owner": "Asha +919876543210",
					"data": f"messaged {ACCOUNT} on WhatsApp: Hello",
					"is_lead": True,
				}
			],
		)

	def test_outgoing_text_row_names_the_crm_user_and_the_number(self):
		self.messages = [make_message(type="Outgoing", to="919876543210", owner="agent@example.com")]

		row = self.rows()[0]

		self.assertEqual(row["owner"], "agent@example.com")
		self.assertEqual(row["data"], "sent a WhatsApp message to +919876543210: Hello")

	def test_outgoing_row_of_a_guest_is_attributed_to_the_account(self):
		# Business-app echoes are saved by the webhook, which runs as Guest.
		self.messages = [make_message(type="Outgoing", to="919876543210", owner="Guest")]
		self.assertEqual(self.rows()[0]["owner"], ACCOUNT)

		self.messages = [make_message(type="Outgoing", to="919876543210", owner="Guest", whatsapp_account=None)]
		self.assertEqual(self.rows()[0]["owner"], "WhatsApp")

	def test_reaction_row_shows_the_emoji(self):
		self.messages = [make_message(content_type="reaction", message="😂")]

		self.assertEqual(self.rows()[0]["data"], "reacted 😂 to a WhatsApp message")

	def test_removed_reaction_row_says_so(self):
		self.messages = [make_message(content_type="reaction", message="")]

		self.assertEqual(self.rows()[0]["data"], "removed a reaction from a WhatsApp message")

	def test_message_without_text_shows_its_content_type(self):
		for body in (None, "", "   ", "<b></b>"):
			for content_type, label in (("image", "[image]"), (None, "[message]"), ("", "[message]")):
				with self.subTest(body=body, content_type=content_type):
					self.messages = [make_message(message=body, content_type=content_type)]
					self.assertTrue(self.rows()[0]["data"].endswith(f": {label}"))

	def test_incoming_row_without_a_profile_name_uses_the_number(self):
		for profile_name in (None, "", "   ", "<b></b>"):
			with self.subTest(profile_name=profile_name):
				self.messages = [make_message(profile_name=profile_name)]
				self.assertEqual(self.rows()[0]["owner"], "+919876543210")

	def test_incoming_row_without_an_account_leaves_the_account_out(self):
		self.messages = [make_message(whatsapp_account=None)]
		self.assertEqual(self.rows()[0]["data"], "messaged on WhatsApp: Hello")

	def test_text_is_plain_one_line_and_cut_at_the_limit(self):
		for body, expected in (
			("<script>alert(1)</script>Hi", "alert(1)Hi"),
			("a\n\n  b\tc", "a b c"),
			("Zoë 😀 李", "Zoë 😀 李"),
			("A" * BODY_MAX_LENGTH, "A" * BODY_MAX_LENGTH),
			("A" * (BODY_MAX_LENGTH + 1), "A" * (BODY_MAX_LENGTH - 1) + "…"),
			("A" * 5000, "A" * (BODY_MAX_LENGTH - 1) + "…"),
		):
			with self.subTest(body=body[:12]):
				self.messages = [make_message(message=body)]
				self.assertTrue(self.rows()[0]["data"].endswith(f": {expected}"))

	def test_an_at_sign_in_a_name_cannot_turn_it_into_an_email(self):
		# The page shows the part before "@" of an owner that is not a user.
		self.messages = [make_message(profile_name="ceo@example.com")]
		self.assertEqual(self.rows()[0]["owner"], "ceoexample.com +919876543210")

	def test_senders_without_digits_still_get_a_row(self):
		for sender in (None, "", "abc"):
			with self.subTest(sender=sender):
				self.messages = [make_message(**{"from": sender}, profile_name=None)]
				self.assertEqual(self.rows()[0]["owner"], "WhatsApp contact")

	def test_every_message_gets_one_row_in_the_order_given(self):
		self.messages = [make_message(name=f"MSG-{n}") for n in range(3)]

		self.assertEqual([row["name"] for row in self.rows()], ["MSG-0", "MSG-1", "MSG-2"])

	# --- failures ----------------------------------------------------------------------

	def test_database_error_is_logged_and_the_crm_answer_is_still_returned(self):
		self.frappe.get_all.side_effect = RuntimeError("db down")

		result = get_activities(LEAD)

		self.assertIs(result, self.crm_result)
		self.assertEqual(result[0], [self.version])
		self.frappe.log_error.assert_called_once_with(title=ERROR_TITLE, message="traceback")

	def test_error_from_crm_itself_is_not_hidden(self):
		self.crm_get_activities.side_effect = PermissionError("Not permitted")

		with self.assertRaises(PermissionError):
			get_activities(LEAD)

		self.frappe.get_all.assert_not_called()

	def test_function_only_reads_the_database(self):
		get_activities(LEAD)
		self.frappe.db.commit.assert_not_called()
		self.frappe.db.rollback.assert_not_called()


if __name__ == "__main__":
	unittest.main()
