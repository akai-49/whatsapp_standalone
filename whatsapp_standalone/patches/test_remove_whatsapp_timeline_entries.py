"""Tests for the patch that removes the WhatsApp timeline entries. `frappe` is mocked; no site is used."""

import unittest
from unittest.mock import call, patch

from whatsapp_standalone.patches.remove_whatsapp_timeline_entries import execute


class TestRemoveWhatsappTimelineEntries(unittest.TestCase):
	def setUp(self):
		patcher = patch("whatsapp_standalone.patches.remove_whatsapp_timeline_entries.frappe")
		self.frappe = patcher.start()
		self.addCleanup(patcher.stop)

	def test_only_chat_entries_made_for_whatsapp_messages_are_selected(self):
		# Emails must never match: both the key prefix and the medium are in the filter.
		self.frappe.get_all.return_value = []

		execute()

		self.frappe.get_all.assert_called_once_with(
			"Communication",
			filters={"message_id": ["like", "whatsapp:%"], "communication_medium": "Chat"},
			pluck="name",
		)

	def test_each_selected_entry_is_deleted(self):
		self.frappe.get_all.return_value = ["COMM-1", "COMM-2"]

		execute()

		self.assertEqual(
			self.frappe.delete_doc.call_args_list,
			[
				call("Communication", "COMM-1", force=True, ignore_permissions=True),
				call("Communication", "COMM-2", force=True, ignore_permissions=True),
			],
		)

	def test_nothing_is_deleted_when_there_are_no_entries(self):
		self.frappe.get_all.return_value = []

		execute()

		self.frappe.delete_doc.assert_not_called()

	def test_running_twice_is_harmless(self):
		self.frappe.get_all.side_effect = [["COMM-1"], []]

		execute()
		execute()

		self.frappe.delete_doc.assert_called_once()


if __name__ == "__main__":
	unittest.main()
