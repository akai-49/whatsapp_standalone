"""Inject custom CRM UI styles into Frappe CRM SPA responses."""

CRM_ROUTE_PREFIX = "/crm"
STYLESHEET_HREF = "/assets/whatsapp_standalone/css/crm_whatsapp_tab.css"
STYLESHEET_TAG = f'<link rel="stylesheet" href="{STYLESHEET_HREF}">'
HTML_MIMETYPE = "text/html"
HEAD_CLOSE_TAG = "</head>"


def inject_crm_tab_order_css(response=None, request=None):
	"""Append our CRM tab-order stylesheet to `/crm` HTML responses.

	Registered as an `after_request` hook because Frappe CRM renders its SPA via a standalone
	`www/crm.html` that does not include Frappe's `app_include_css` or `web_include_css`.
	Injecting only the stylesheet link leaves CRM's hashed Vite assets untouched across upgrades.

	Args:
		response: Werkzeug response object from the request lifecycle.
		request: Werkzeug request object from the request lifecycle.

	Side effects: modifies `response` data in place for 2xx HTML responses under `/crm`.
	"""
	if not _should_inject(response, request):
		return

	html = response.get_data(as_text=True)
	if not isinstance(html, str) or STYLESHEET_HREF in html:
		return

	head_close_index = html.lower().find(HEAD_CLOSE_TAG)
	if head_close_index == -1:
		return

	response.set_data(f"{html[:head_close_index]}{STYLESHEET_TAG}\n{html[head_close_index:]}")


def _should_inject(response, request):
	"""Return True when `response` is a 2xx HTML page served under `/crm`."""
	if response is None or request is None:
		return False

	path = getattr(request, "path", None) or ""
	if path != CRM_ROUTE_PREFIX and not path.startswith(f"{CRM_ROUTE_PREFIX}/"):
		return False

	status_code = getattr(response, "status_code", None)
	if not isinstance(status_code, int) or not (200 <= status_code < 300):
		return False

	mimetype = (getattr(response, "mimetype", None) or "").lower()
	if mimetype != HTML_MIMETYPE:
		return False

	return not getattr(response, "direct_passthrough", False)
