"""Tests for the records this app ships (fixtures) and the hooks that point at them."""

import importlib
import json
import os
import unittest

from whatsapp_standalone import hooks

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")
LEAD_SOURCE_FILE = "crm_lead_source.json"
NOTIFICATION_FILE = "notification.json"
SOURCE_NAME = "WhatsApp"
NOTIFICATION_NAME = "New WhatsApp Lead"


def load_fixture(file_name):
	with open(os.path.join(FIXTURES_DIR, file_name)) as fixture_file:
		return json.load(fixture_file)


class TestFixtures(unittest.TestCase):
	def test_lead_source_fixture(self):
		records = load_fixture(LEAD_SOURCE_FILE)

		self.assertEqual(len(records), 1)
		self.assertEqual(records[0]["doctype"], "CRM Lead Source")
		self.assertEqual(records[0]["source_name"], SOURCE_NAME)
		# Frappe's fixture import reads `name` unconditionally; without it `bench migrate` fails.
		self.assertEqual(records[0]["name"], SOURCE_NAME)

	def test_notification_fixture_targets_new_whatsapp_leads(self):
		records = load_fixture(NOTIFICATION_FILE)

		self.assertEqual(len(records), 1)
		notification = records[0]
		self.assertEqual(notification["doctype"], "Notification")
		self.assertEqual(notification["name"], NOTIFICATION_NAME)
		self.assertEqual(notification["document_type"], "CRM Lead")
		self.assertEqual(notification["event"], "New")
		self.assertEqual(notification["channel"], "System Notification")
		self.assertEqual(notification["condition"], f'doc.source == "{SOURCE_NAME}"')
		self.assertTrue(notification["enabled"])
		self.assertTrue(notification["subject"])
		self.assertTrue(notification["message"])

	def test_notification_goes_to_sales_managers_and_the_lead_owner(self):
		recipients = load_fixture(NOTIFICATION_FILE)[0]["recipients"]

		self.assertIn("Sales Manager", [row.get("receiver_by_role") for row in recipients])
		self.assertIn("lead_owner", [row.get("receiver_by_document_field") for row in recipients])

	def test_every_fixture_record_has_a_doctype_and_a_name(self):
		for file_name in (LEAD_SOURCE_FILE, NOTIFICATION_FILE):
			for record in load_fixture(file_name):
				with self.subTest(file=file_name):
					self.assertTrue(record.get("doctype"))
					self.assertTrue(record.get("name"))

	def test_lead_source_loads_before_the_notification(self):
		files = sorted(name for name in os.listdir(FIXTURES_DIR) if name.endswith(".json"))

		self.assertLess(files.index(LEAD_SOURCE_FILE), files.index(NOTIFICATION_FILE))

	def test_the_source_the_notification_checks_is_the_source_that_is_shipped(self):
		source = load_fixture(LEAD_SOURCE_FILE)[0]["source_name"]
		condition = load_fixture(NOTIFICATION_FILE)[0]["condition"]

		self.assertIn(f'"{source}"', condition)


class TestHooks(unittest.TestCase):
	def test_incoming_message_handler_is_registered_and_importable(self):
		handler = hooks.doc_events["WhatsApp Message"]["after_insert"][0]

		module_name, function_name = handler.rsplit(".", 1)
		self.assertTrue(callable(getattr(importlib.import_module(module_name), function_name)))

	def test_timeline_entry_is_made_after_the_lead_exists(self):
		handlers = hooks.doc_events["WhatsApp Message"]["after_insert"]

		self.assertEqual(
			handlers,
			[
				"whatsapp_standalone.incoming_leads.create_lead_for_incoming_message",
				"whatsapp_standalone.whatsapp_timeline.mirror_message_to_timeline",
			],
		)
		for handler in handlers:
			module_name, function_name = handler.rsplit(".", 1)
			self.assertTrue(callable(getattr(importlib.import_module(module_name), function_name)))

	def test_email_is_linked_before_crm_looks_at_it(self):
		# `before_insert`, so CRM's own `after_insert` sees a linked email and makes no second lead.
		handler = hooks.doc_events["Communication"]["before_insert"]

		module_name, function_name = handler.rsplit(".", 1)
		self.assertEqual(handler, "whatsapp_standalone.email_linking.link_email_to_lead")
		self.assertTrue(callable(getattr(importlib.import_module(module_name), function_name)))

	def test_echo_handler_registration_is_kept(self):
		self.assertEqual(
			hooks.doc_events["WhatsApp Notification Log"]["after_insert"],
			"whatsapp_standalone.echoes.sync_message_echoes",
		)

	def test_fixtures_hook_exports_the_shipped_records(self):
		exported = {entry["dt"]: entry["filters"] for entry in hooks.fixtures}

		self.assertEqual(exported["CRM Lead Source"], [["name", "=", SOURCE_NAME]])
		self.assertEqual(exported["Notification"], [["name", "=", NOTIFICATION_NAME]])


if __name__ == "__main__":
	unittest.main()
