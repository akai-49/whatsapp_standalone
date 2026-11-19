"""Tests for lead creation from incoming WhatsApp messages. `frappe` is mocked; no site or database is used."""

import re
import unittest
from unittest.mock import MagicMock, patch

from redis.exceptions import ConnectionError as RedisConnectionError

from whatsapp_standalone.incoming_leads import create_lead_for_incoming_message

SITE = "example.test"
NUMBER = "919876543210"
ERROR_TITLE = "WhatsApp lead create failed"
NAME_MAX_LENGTH = 140


class FakeMessage:
	"""Stand-in `WhatsApp Message`; `from` is a Python keyword, so it is read through `get`."""

	def __init__(self, **values):
		self.__dict__.update(values)

	def get(self, key, default=None):
		return self.__dict__.get(key, default)


def make_message(sender=NUMBER, message_type="Incoming", profile_name="Asha"):
	return FakeMessage(**{"name": "MSG-1", "type": message_type, "from": sender, "profile_name": profile_name})


class TestCreateLeadForIncomingMessage(unittest.TestCase):
	def setUp(self):
		patcher = patch("whatsapp_standalone.incoming_leads.frappe")
		self.frappe = patcher.start()
		self.addCleanup(patcher.stop)

		self.events = []
		self.after_commit = []
		self.after_rollback = []
		self.frappe.local.site = SITE
		self.frappe.get_installed_apps.return_value = ["frappe", "crm"]
		self.frappe.get_traceback.return_value = "traceback"
		self.frappe.utils.strip_html.side_effect = lambda text: re.sub(r"<[^>]*>", "", text)
		self.frappe.db.sql.side_effect = self._sql
		self.frappe.db.after_commit.add.side_effect = self.after_commit.append
		self.frappe.db.after_rollback.add.side_effect = self.after_rollback.append
		self.frappe.get_doc.side_effect = self._get_doc

		self.lock = MagicMock()
		self.lock.acquire.side_effect = lambda *a, **k: self.events.append("acquire") or True
		self.lock.release.side_effect = lambda: self.events.append("release")
		self.frappe.cache.lock.return_value = self.lock

		self.existing_in = set()  # doctypes that already hold the number
		self.inserted = []

	def _sql(self, query, values=None, *args, **kwargs):
		self.events.append("sql")
		return [("EXISTING",)] if any(f"`tab{doctype}`" in query for doctype in self.existing_in) else []

	def _get_doc(self, values):
		doc = MagicMock(values=values)
		doc.insert.side_effect = lambda **kwargs: self.events.append("insert") or self.inserted.append(values)
		return doc

	def run_handler(self, message):
		create_lead_for_incoming_message(message)

	def commit(self):
		"""Run the callbacks `frappe.db.commit` would run."""
		for callback in self.after_commit:
			callback()

	def rollback(self):
		"""Run the callbacks a full `frappe.db.rollback` would run."""
		for callback in self.after_rollback:
			callback()

	def assert_skipped(self):
		self.frappe.cache.lock.assert_not_called()
		self.frappe.get_doc.assert_not_called()

	# --- inputs that must be ignored -------------------------------------------------

	def test_non_incoming_messages_are_ignored(self):
		for message_type in ("Outgoing", "", None, "incoming"):
			with self.subTest(message_type=message_type):
				self.run_handler(make_message(message_type=message_type))
				self.assert_skipped()

	def test_senders_without_digits_are_ignored(self):
		for sender in (None, "", "   ", "+-", "abc", 123456, ["919876543210"], {}):
			with self.subTest(sender=sender):
				self.run_handler(make_message(sender=sender))
				self.assert_skipped()

	def test_echo_saved_as_outgoing_does_not_create_a_lead(self):
		self.run_handler(make_message(message_type="Outgoing"))
		self.assert_skipped()

	def test_nothing_happens_when_crm_is_not_installed(self):
		self.frappe.get_installed_apps.return_value = ["frappe"]

		self.run_handler(make_message())

		self.assert_skipped()
		self.frappe.db.sql.assert_not_called()
		self.frappe.log_error.assert_not_called()

	# --- lead values -----------------------------------------------------------------

	def test_new_number_creates_a_lead_with_source_and_status(self):
		self.run_handler(make_message())

		self.assertEqual(
			self.inserted,
			[
				{
					"doctype": "CRM Lead",
					"first_name": "Asha",
					"mobile_no": "+919876543210",
					"source": "WhatsApp",
					"status": "New",
				}
			],
		)

	def test_lead_is_inserted_without_permission_checks(self):
		docs = []

		def get_doc(values):
			doc = MagicMock()
			docs.append(doc)
			return doc

		self.frappe.get_doc.side_effect = get_doc
		self.run_handler(make_message())
		docs[0].insert.assert_called_once_with(ignore_permissions=True)

	def test_formatted_numbers_are_reduced_to_digits(self):
		for sender in ("+91 98765-43210", "(91) 98765 43210", " 919876543210 ", "+919876543210"):
			with self.subTest(sender=sender):
				self.inserted.clear()
				self.run_handler(make_message(sender=sender))
				self.assertEqual(self.inserted[0]["mobile_no"], "+919876543210")

	def test_first_name_falls_back_to_the_number(self):
		for profile_name in (None, "", "   ", "\t\n", "<b></b>", "<script>", 42):
			with self.subTest(profile_name=profile_name):
				self.inserted.clear()
				self.run_handler(make_message(profile_name=profile_name))
				self.assertEqual(self.inserted[0]["first_name"], NUMBER)

	def test_first_name_is_a_plain_name_that_fits_the_field(self):
		for profile_name, expected in (
			("  Asha  ", "Asha"),
			("Zoë 😀 李", "Zoë 😀 李"),
			("<b>Asha</b>", "Asha"),
			("A" * 500, "A" * NAME_MAX_LENGTH),
			("A" * NAME_MAX_LENGTH, "A" * NAME_MAX_LENGTH),
			("A" * (NAME_MAX_LENGTH + 1), "A" * NAME_MAX_LENGTH),
		):
			with self.subTest(profile_name=profile_name[:20]):
				self.inserted.clear()
				self.run_handler(make_message(profile_name=profile_name))
				self.assertEqual(self.inserted[0]["first_name"], expected)

	# --- duplicates ------------------------------------------------------------------

	def test_existing_lead_or_deal_prevents_a_new_lead(self):
		for doctypes in ({"CRM Lead"}, {"CRM Deal"}, {"CRM Lead", "CRM Deal"}):
			with self.subTest(doctypes=sorted(doctypes)):
				self.existing_in = doctypes
				self.frappe.get_doc.reset_mock()
				self.run_handler(make_message())
				self.frappe.get_doc.assert_not_called()

	def test_match_query_strips_separators_in_both_number_columns(self):
		# The comparison runs in SQL, so the query shape is what is verified here: stored values
		# such as "+91 90195 32735", "+91-98765-43210" and "(91) 98765.43210" are reduced to
		# digits the same way, in `mobile_no` and in `phone`.
		self.run_handler(make_message())

		queries = [call.args[0] for call in self.frappe.db.sql.call_args_list]
		self.assertEqual(len(queries), 2)
		for query in queries:
			for column in ("mobile_no", "phone"):
				with self.subTest(column=column):
					expression = column
					for separator in (" ", "+", "-", "(", ")", "."):
						expression = f"replace({expression}, '{separator}', '')"
					self.assertIn(f"{expression} = %s", query)
			self.assertIn("limit 1", query.lower())
		self.assertTrue(any("`tabCRM Lead`" in query for query in queries))
		self.assertTrue(any("`tabCRM Deal`" in query for query in queries))

	def test_number_is_passed_as_a_bind_parameter(self):
		payload = "1'; DROP TABLE `tabCRM Lead`;--"
		self.run_handler(make_message(sender=payload))

		for call in self.frappe.db.sql.call_args_list:
			self.assertNotIn("DROP", call.args[0])
			self.assertEqual(call.args[1], ("1", "1"))

	def test_number_already_a_lead_never_gets_a_second_lead(self):
		self.run_handler(make_message())
		self.assertEqual(len(self.inserted), 1)

		self.existing_in = {"CRM Lead"}
		self.run_handler(make_message())
		self.assertEqual(len(self.inserted), 1)

	# --- locking ---------------------------------------------------------------------

	def test_lock_name_holds_the_site_and_the_number(self):
		self.run_handler(make_message())

		name = self.frappe.cache.lock.call_args.args[0]
		self.assertIn(SITE, name)
		self.assertIn(NUMBER, name)

	def test_check_and_insert_happen_while_the_lock_is_held(self):
		self.run_handler(make_message())
		self.assertEqual(self.events, ["acquire", "sql", "sql", "insert"])

	def test_lock_is_held_until_the_transaction_commits(self):
		# Until the commit the new lead is invisible to other requests; an earlier release would
		# let a second message from the same number miss it and create a duplicate.
		self.run_handler(make_message())
		self.lock.release.assert_not_called()

		self.commit()

		self.assertEqual(self.events[-1], "release")
		self.lock.release.assert_called_once()

	def test_lock_is_released_after_a_rollback_too(self):
		self.run_handler(make_message())

		self.rollback()

		self.lock.release.assert_called_once()

	def test_lock_is_released_after_the_check_finds_a_lead(self):
		self.existing_in = {"CRM Lead"}
		self.run_handler(make_message())
		self.assertEqual(self.events, ["acquire", "sql"])

		self.commit()

		self.assertEqual(self.events, ["acquire", "sql", "release"])

	def test_lock_that_cannot_be_acquired_skips_the_insert_and_is_logged(self):
		self.lock.acquire.side_effect = lambda *a, **k: self.events.append("acquire") or False

		self.run_handler(make_message())

		self.assertEqual(self.events, ["acquire"])
		self.assertEqual(self.after_commit + self.after_rollback, [])
		self.lock.release.assert_not_called()
		self.assertEqual(self.inserted, [])
		self.frappe.log_error.assert_called_once()

	def test_redis_error_on_release_does_not_raise_or_undo_the_lead(self):
		self.lock.release.side_effect = RedisConnectionError("redis down")

		self.run_handler(make_message())
		self.commit()

		self.frappe.db.rollback.assert_not_called()
		self.assertEqual(len(self.inserted), 1)

	# --- failures --------------------------------------------------------------------

	def test_failed_insert_is_rolled_back_logged_and_never_raised(self):
		self.frappe.get_doc.side_effect = lambda values: MagicMock(
			insert=MagicMock(side_effect=ValueError("boom"))
		)

		self.run_handler(make_message())

		self.frappe.db.savepoint.assert_called_once()
		self.frappe.db.rollback.assert_called_once_with(save_point=self.frappe.db.savepoint.call_args.args[0])
		self.frappe.log_error.assert_called_once_with(title=ERROR_TITLE, message="traceback")
		self.lock.release.assert_not_called()

		self.commit()

		self.lock.release.assert_called_once()

	def test_database_error_during_the_check_is_logged_and_never_raised(self):
		self.frappe.db.sql.side_effect = RuntimeError("db down")

		self.run_handler(make_message())

		self.frappe.log_error.assert_called_once_with(title=ERROR_TITLE, message="traceback")
		self.frappe.get_doc.assert_not_called()

		self.commit()

		self.lock.release.assert_called_once()

	def test_redis_failure_is_logged_and_never_raised(self):
		self.frappe.cache.lock.side_effect = ConnectionError("redis down")

		self.run_handler(make_message())

		self.frappe.log_error.assert_called_once_with(title=ERROR_TITLE, message="traceback")
		self.frappe.get_doc.assert_not_called()

	def test_handler_never_commits(self):
		self.run_handler(make_message())
		self.frappe.db.commit.assert_not_called()


if __name__ == "__main__":
	unittest.main()
