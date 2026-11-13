"""Tests for the CRM WhatsApp shim. CRM is replaced with stub modules; no site or database is used."""

import sys
import types
import unittest
from unittest.mock import patch

from whatsapp_standalone.overrides.crm_whatsapp import use_unchecked_assignee_lookup


def checked_lookup(doctype, name):
	"""Stand-in for CRM's whitelisted `get_assigned_users`: always denies, as it does for Guest."""
	raise PermissionError("No permission for CRM Lead")


def unchecked_lookup(doctype, name):
	"""Stand-in for CRM's internal `get_assignees`."""
	return ["agent@example.com"]


def make_crm_modules(with_bug: bool):
	"""Build stub `crm` modules. `with_bug` gives `crm.api.whatsapp` the unfixed import."""
	crm, api = types.ModuleType("crm"), types.ModuleType("crm.api")
	doc, whatsapp = types.ModuleType("crm.api.doc"), types.ModuleType("crm.api.whatsapp")
	doc.get_assigned_users = checked_lookup
	doc.get_assignees = unchecked_lookup
	if with_bug:
		whatsapp.get_assigned_users = checked_lookup
	else:
		whatsapp.get_assignees = unchecked_lookup
	crm.api, api.doc, api.whatsapp = api, doc, whatsapp
	return {"crm": crm, "crm.api": api, "crm.api.doc": doc, "crm.api.whatsapp": whatsapp}


class TestUseUncheckedAssigneeLookup(unittest.TestCase):
	def test_unfixed_crm_gets_the_unchecked_lookup(self):
		modules = make_crm_modules(with_bug=True)
		with patch.dict(sys.modules, modules):
			use_unchecked_assignee_lookup()
			use_unchecked_assignee_lookup()  # runs on every request, so it must be repeatable

		whatsapp = modules["crm.api.whatsapp"]
		self.assertEqual(whatsapp.get_assigned_users("CRM Lead", "LEAD-1"), ["agent@example.com"])

	def test_whitelisted_api_keeps_its_permission_check(self):
		modules = make_crm_modules(with_bug=True)
		with patch.dict(sys.modules, modules):
			use_unchecked_assignee_lookup()

		with self.assertRaises(PermissionError):
			modules["crm.api.doc"].get_assigned_users("CRM Lead", "LEAD-1")

	def test_fixed_crm_is_left_alone(self):
		modules = make_crm_modules(with_bug=False)
		with patch.dict(sys.modules, modules):
			use_unchecked_assignee_lookup()

		self.assertFalse(hasattr(modules["crm.api.whatsapp"], "get_assigned_users"))

	def test_does_nothing_when_crm_is_not_installed(self):
		with patch.dict(sys.modules, {"crm": None}):
			use_unchecked_assignee_lookup()  # must not raise


if __name__ == "__main__":
	unittest.main()
