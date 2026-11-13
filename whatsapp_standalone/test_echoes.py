"""Tests for the Business-app echo sync. `frappe` is mocked; no site or database is used."""

import json
import types
from datetime import datetime
import unittest
from unittest.mock import MagicMock, patch

from whatsapp_standalone.echoes import sync_message_echoes

PHONE_ID = "PHONE-ID-1"
CUSTOMER = "15550001111"


def make_log(echoes, field="smb_message_echoes", template="Webhook", key="message_echoes"):
	"""Build a stand-in `WhatsApp Notification Log` holding one webhook change."""
	value = {"metadata": {"phone_number_id": PHONE_ID}, key: echoes}
	payload = {"entry": [{"changes": [{"field": field, "value": value}]}]}
	return types.SimpleNamespace(name="LOG-1", template=template, meta_data=json.dumps(payload))


def text_echo(message_id="wamid.A", body="Sure"):
	return {
		"from": "15559990000",
		"to": CUSTOMER,
		"id": message_id,
		"timestamp": "1794589995",
		"type": "text",
		"text": {"body": body},
	}


class TestSyncMessageEchoes(unittest.TestCase):
	def setUp(self):
		patcher = patch("whatsapp_standalone.echoes.frappe")
		self.frappe = patcher.start()
		self.addCleanup(patcher.stop)
		self.frappe.db.exists.return_value = None
		self.frappe.db.get_value.return_value = "Main Account"
		self.frappe.get_doc.side_effect = lambda values: MagicMock(values=values)

	def saved_values(self):
		return [call.args[0] for call in self.frappe.get_doc.call_args_list]

	def test_text_echo_is_saved_as_outgoing_message(self):
		sync_message_echoes(make_log([text_echo()]))

		self.assertEqual(
			self.saved_values(),
			[
				{
					"doctype": "WhatsApp Message",
					"type": "Outgoing",
					"to": CUSTOMER,
					"message": "Sure",
					"message_id": "wamid.A",
					"content_type": "text",
					"status": "sent",
					"whatsapp_account": "Main Account",
				}
			],
		)

	def test_echo_is_inserted_without_sending_it_to_meta_again(self):
		docs = []
		self.frappe.get_doc.side_effect = lambda values: docs.append(MagicMock()) or docs[-1]

		sync_message_echoes(make_log([text_echo()]))

		doc = docs[0]
		self.assertNotIsInstance(doc.send_outgoing, MagicMock)  # replaced with a no-op
		self.assertIsNone(doc.send_outgoing())
		doc.insert.assert_called_once_with(ignore_permissions=True)

	def test_message_keeps_the_time_it_was_sent(self):
		docs = []
		self.frappe.get_doc.side_effect = lambda values: docs.append(MagicMock()) or docs[-1]
		self.frappe.utils.convert_utc_to_system_timezone.side_effect = lambda value: value

		sync_message_echoes(make_log([text_echo()]))

		args, kwargs = docs[0].db_set.call_args
		self.assertEqual(args[0], "creation")
		self.assertEqual(args[1], datetime(2026, 11, 13, 17, 13, 15))  # 1794589995 as naive UTC
		self.assertEqual(kwargs, {"update_modified": False})

	def test_reaction_echo_points_at_the_reacted_message(self):
		echo = {"to": CUSTOMER, "id": "wamid.R", "type": "reaction", "reaction": {"message_id": "wamid.X", "emoji": "👍"}}

		sync_message_echoes(make_log([echo]))

		saved = self.saved_values()[0]
		self.assertEqual(saved["content_type"], "reaction")
		self.assertEqual(saved["message"], "👍")
		self.assertEqual(saved["reply_to_message_id"], "wamid.X")

	def test_every_echo_in_one_webhook_is_saved(self):
		sync_message_echoes(make_log([text_echo("wamid.A"), text_echo("wamid.B", "💀")]))

		self.assertEqual([v["message_id"] for v in self.saved_values()], ["wamid.A", "wamid.B"])

	def test_duplicate_message_id_is_skipped(self):
		self.frappe.db.exists.return_value = "MSG-EXISTING"

		sync_message_echoes(make_log([text_echo()]))

		self.frappe.get_doc.assert_not_called()

	def test_account_is_left_to_the_default_when_phone_id_is_unknown(self):
		self.frappe.db.get_value.return_value = None

		sync_message_echoes(make_log([text_echo()]))

		self.assertNotIn("whatsapp_account", self.saved_values()[0])

	def test_ignored_payloads_save_nothing(self):
		ignored = {
			"customer message webhook": make_log([text_echo()], field="messages", key="messages"),
			"other log type": make_log([text_echo()], template="Text Message"),
			"media echo": make_log([{"to": CUSTOMER, "id": "wamid.I", "type": "image", "image": {"id": "1"}}]),
			"echo without id": make_log([{"to": CUSTOMER, "type": "text", "text": {"body": "x"}}]),
			"echo without recipient": make_log([{"id": "wamid.N", "type": "text", "text": {"body": "x"}}]),
			"empty text": make_log([text_echo(body="")]),
			"empty echo list": make_log([]),
			"invalid json": types.SimpleNamespace(name="L", template="Webhook", meta_data="{not json"),
			"missing meta_data": types.SimpleNamespace(name="L", template="Webhook", meta_data=None),
			"json list": types.SimpleNamespace(name="L", template="Webhook", meta_data="[]"),
			"entry not a list": types.SimpleNamespace(name="L", template="Webhook", meta_data='{"entry": 5}'),
		}
		for label, log in ignored.items():
			with self.subTest(label):
				sync_message_echoes(log)
				self.frappe.get_doc.assert_not_called()

	def test_a_failed_save_is_rolled_back_and_logged_and_does_not_break_the_webhook(self):
		self.frappe.get_doc.side_effect = RuntimeError("db down")

		sync_message_echoes(make_log([text_echo()]))  # must not raise

		self.frappe.db.rollback.assert_called_once_with(save_point="whatsapp_echo")
		self.frappe.log_error.assert_called_once()


if __name__ == "__main__":
	unittest.main()
