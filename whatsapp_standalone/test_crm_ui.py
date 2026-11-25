"""Tests for injecting the CRM tab-order stylesheet into `/crm` HTML responses."""

import os
import unittest
from types import SimpleNamespace

from whatsapp_standalone.crm_ui import STYLESHEET_HREF, STYLESHEET_TAG, inject_crm_tab_order_css

SAMPLE_HTML = (
	"<!doctype html><html><head><title>Frappe CRM</title></head>"
	"<body><div id='app'></div></body></html>"
)
CSS_PATH = os.path.join(os.path.dirname(__file__), "public", "css", "crm_whatsapp_tab.css")


class FakeResponse:
	"""Minimal stand-in for Werkzeug's `Response`."""

	def __init__(self, body=SAMPLE_HTML, status_code=200, mimetype="text/html", direct_passthrough=False):
		self.body = body
		self.status_code = status_code
		self.mimetype = mimetype
		self.direct_passthrough = direct_passthrough

	def get_data(self, as_text=False):
		return self.body if as_text else self.body.encode("utf-8")

	def set_data(self, data):
		self.body = data


class TestInjectCrmTabOrderCss(unittest.TestCase):
	def test_injects_stylesheet_for_crm_root_and_subroutes(self):
		for path in ("/crm", "/crm/leads/CRM-LEAD-1", "/crm/deals/CRM-DEAL-1"):
			with self.subTest(path=path):
				response = FakeResponse()
				inject_crm_tab_order_css(response=response, request=SimpleNamespace(path=path))
				self.assertIn(f"{STYLESHEET_TAG}\n</head>", response.body)

	def test_handles_uppercase_head_close_tag(self):
		response = FakeResponse(body="<HTML><HEAD></HEAD><BODY></BODY></HTML>")
		inject_crm_tab_order_css(response=response, request=SimpleNamespace(path="/crm"))
		self.assertEqual(response.body, f"<HTML><HEAD>{STYLESHEET_TAG}\n</HEAD><BODY></BODY></HTML>")

	def test_is_idempotent_if_already_injected(self):
		already = f"<html><head>{STYLESHEET_TAG}</head><body></body></html>"
		response = FakeResponse(body=already)
		inject_crm_tab_order_css(response=response, request=SimpleNamespace(path="/crm"))
		self.assertEqual(response.body, already)
		self.assertEqual(response.body.count(STYLESHEET_HREF), 1)

	def test_skips_non_crm_routes(self):
		for path in ("/", "/app", "/crm-form/lead", "/api/method/crm.api.activities.get_activities", ""):
			with self.subTest(path=path):
				response = FakeResponse()
				inject_crm_tab_order_css(response=response, request=SimpleNamespace(path=path))
				self.assertEqual(response.body, SAMPLE_HTML)

	def test_skips_non_2xx_non_html_and_passthrough_responses(self):
		for kwargs in (
			{"status_code": 302},
			{"status_code": 404},
			{"status_code": 500},
			{"mimetype": "application/json", "body": '{"ok": true}'},
			{"mimetype": "text/css", "body": "body {}"},
			{"direct_passthrough": True},
		):
			with self.subTest(kwargs=kwargs):
				original = kwargs.get("body", SAMPLE_HTML)
				response = FakeResponse(**kwargs)
				inject_crm_tab_order_css(response=response, request=SimpleNamespace(path="/crm"))
				self.assertEqual(response.body, original)

	def test_handles_missing_head_tag_or_missing_request_or_response(self):
		response = FakeResponse(body="<div>no head</div>")
		inject_crm_tab_order_css(response=response, request=SimpleNamespace(path="/crm"))
		self.assertEqual(response.body, "<div>no head</div>")

		inject_crm_tab_order_css(response=None, request=SimpleNamespace(path="/crm"))
		inject_crm_tab_order_css(response=response, request=None)

	def test_css_asset_exists_and_orders_whatsapp_after_activity(self):
		with open(CSS_PATH) as css_file:
			css = css_file.read()

		self.assertIn('[id$="-trigger-details"]', css)
		self.assertIn('[id$="-trigger-activity"]', css)
		self.assertIn('[id$="-trigger-whatsapp"]', css)
		self.assertIn("order: -3;", css)
		self.assertIn("order: -2;", css)
		self.assertIn("order: -1;", css)


if __name__ == "__main__":
	unittest.main()
