"""Tests for the lead timeline entry of a WhatsApp message. `frappe` is mocked; no site or database is used."""

import html
import unittest
from unittest.mock import MagicMock, patch

from whatsapp_standalone.whatsapp_timeline import mirror_message_to_timeline

NUMBER = "919876543210"
CREATED = "2026-11-19 10:00:00"
ERROR_TITLE = "WhatsApp timeline entry failed"


class FakeMessage:
	"""Stand-in `WhatsApp Message`; `from` is a Python keyword, so it is read through `get`."""

	def __init__(self, **values):
		self.__dict__.update(values)

	def get(self, key, default=None):
		return self.__dict__.get(key, default)


def make_message(message_type="Incoming", **extra):
	values = {
		"name": "MSG-1",
		"type": message_type,
		"from": NUMBER if message_type == "Incoming" else "",
		"to": "" if message_type == "Incoming" else NUMBER,
		"profile_name": "Asha",
		"message": "Hello",
		"content_type": "text",
		"creation": CREATED,
		"reference_doctype": "CRM Lead",
		"reference_name": "CRM-LEAD-1",
	}
	return FakeMessage(**{**values, **extra})


class TestMirrorMessageToTimeline(unittest.TestCase):
	def setUp(self):
		patcher = patch("whatsapp_standalone.whatsapp_timeline.frappe")
		self.frappe = patcher.start()
		self.addCleanup(patcher.stop)

		self.frappe.get_traceback.return_value = "traceback"
		self.frappe.utils.escape_html.side_effect = html.escape
		self.frappe.db.exists.return_value = None
		self.docs = []
		self.frappe.get_doc.side_effect = self._get_doc

	def _get_doc(self, values):
		doc = MagicMock(values=values)
		self.docs.append(doc)
		return doc

	def values(self):
		return self.docs[0].values

	def assert_skipped(self):
		self.frappe.get_doc.assert_not_called()

	# --- messages that get no entry ---------------------------------------------------

	def test_messages_without_a_lead_or_deal_are_skipped(self):
		for reference in (
			{"reference_doctype": None, "reference_name": None},
			{"reference_doctype": "", "reference_name": ""},
			{"reference_doctype": "CRM Lead", "reference_name": None},
			{"reference_doctype": None, "reference_name": "CRM-LEAD-1"},
			{"reference_doctype": "ToDo", "reference_name": "TODO-1"},
			{"reference_doctype": "Communication", "reference_name": "COMM-1"},
		):
			with self.subTest(reference=reference):
				mirror_message_to_timeline(make_message(**reference))
				self.assert_skipped()

	def test_a_message_that_has_an_entry_gets_no_second_one(self):
		self.frappe.db.exists.return_value = "COMM-1"

		mirror_message_to_timeline(make_message())

		self.assert_skipped()
		self.frappe.db.exists.assert_called_once_with("Communication", {"message_id": "whatsapp:MSG-1"})

	# --- entry values ------------------------------------------------------------------

	def test_incoming_message_becomes_a_received_chat_entry_on_the_lead(self):
		mirror_message_to_timeline(make_message())

		self.assertEqual(
			self.values(),
			{
				"doctype": "Communication",
				"communication_type": "Communication",
				"communication_medium": "Chat",
				"sent_or_received": "Received",
				"subject": f"WhatsApp message from +{NUMBER}",
				"content": "Hello",
				"sender_full_name": "Asha",
				"communication_date": CREATED,
				"message_id": "whatsapp:MSG-1",
				"reference_doctype": "CRM Lead",
				"reference_name": "CRM-LEAD-1",
			},
		)
		self.docs[0].insert.assert_called_once_with(ignore_permissions=True)

	def test_outgoing_message_becomes_a_sent_entry_on_the_deal(self):
		mirror_message_to_timeline(
			make_message("Outgoing", reference_doctype="CRM Deal", reference_name="CRM-DEAL-1")
		)

		values = self.values()
		self.assertEqual(values["sent_or_received"], "Sent")
		self.assertEqual(values["subject"], f"WhatsApp message to +{NUMBER}")
		self.assertEqual(values["sender_full_name"], "WhatsApp")
		self.assertEqual((values["reference_doctype"], values["reference_name"]), ("CRM Deal", "CRM-DEAL-1"))

	def test_sender_name_falls_back_to_the_number(self):
		for profile_name in (None, "", "   "):
			with self.subTest(profile_name=profile_name):
				self.docs.clear()
				mirror_message_to_timeline(make_message(profile_name=profile_name))
				self.assertEqual(self.values()["sender_full_name"], f"+{NUMBER}")

	def test_entry_never_holds_a_phone_number_in_an_email_field(self):
		# Communication validates `sender`, `recipients` and `cc` as email addresses.
		mirror_message_to_timeline(make_message())
		mirror_message_to_timeline(make_message("Outgoing"))

		for doc in self.docs:
			for field in ("sender", "recipients", "cc", "bcc"):
				self.assertNotIn(field, doc.values)

	def test_empty_body_shows_the_content_type(self):
		for body in (None, "", "   ", "\n"):
			for content_type, label in (("image", "[image]"), (None, "[message]"), ("", "[message]")):
				with self.subTest(body=body, content_type=content_type):
					self.docs.clear()
					mirror_message_to_timeline(make_message(message=body, content_type=content_type))
					self.assertEqual(self.values()["content"], label)

	def test_body_is_escaped_so_a_sender_cannot_inject_markup(self):
		for body in ("<script>alert(1)</script>", "<img src=x onerror=alert(1)>", "a & b"):
			with self.subTest(body=body):
				self.docs.clear()
				mirror_message_to_timeline(make_message(message=body))
				self.assertEqual(self.values()["content"], html.escape(body))

	def test_unicode_emoji_and_long_bodies_pass_through(self):
		for body in ("Zoë 😀 李", "A" * 5000):
			with self.subTest(body=body[:10]):
				self.docs.clear()
				mirror_message_to_timeline(make_message(message=body))
				self.assertEqual(self.values()["content"], body)

	# --- failures ----------------------------------------------------------------------

	def test_failed_insert_is_rolled_back_logged_and_never_raised(self):
		self.frappe.get_doc.side_effect = lambda values: MagicMock(
			insert=MagicMock(side_effect=ValueError("boom"))
		)

		mirror_message_to_timeline(make_message())

		self.frappe.db.savepoint.assert_called_once()
		self.frappe.db.rollback.assert_called_once_with(save_point=self.frappe.db.savepoint.call_args.args[0])
		self.frappe.log_error.assert_called_once_with(title=ERROR_TITLE, message="traceback")

	def test_database_error_on_the_duplicate_check_is_logged_and_never_raised(self):
		self.frappe.db.exists.side_effect = RuntimeError("db down")

		mirror_message_to_timeline(make_message())

		self.frappe.log_error.assert_called_once_with(title=ERROR_TITLE, message="traceback")
		self.assert_skipped()

	def test_handler_never_commits(self):
		mirror_message_to_timeline(make_message())
		self.frappe.db.commit.assert_not_called()


if __name__ == "__main__":
	unittest.main()
