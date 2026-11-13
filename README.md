### WhatsApp Standalone

WhatsApp integration fixes and extensions for Frappe CRM

### Installation

You can install this app using the [bench](https://github.com/frappe/bench) CLI:

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app $URL_OF_THIS_REPO --branch version-16
bench install-app whatsapp_standalone
```

### Contributing

This app uses `pre-commit` for code formatting and linting. Please [install pre-commit](https://pre-commit.com/#installation) and enable it for this repository:

```bash
cd apps/whatsapp_standalone
pre-commit install
```

Pre-commit is configured to use the following tools for checking and formatting your code:

- ruff
- eslint
- prettier
- pyupgrade

### License

mit

### What it does

**Incoming WhatsApp replies on Frappe CRM version-16**

With `frappe_whatsapp` and Frappe CRM v16.0.3, a reply from a number that matches a lead or deal is not saved. The webhook runs as Guest, CRM's `notify_agent` checks read permission on the lead, and the request fails with HTTP 403.

This app applies the upstream fix ([frappe/crm#3214](https://github.com/frappe/crm/pull/3214)) at runtime through a `before_request` hook (`whatsapp_standalone/overrides/crm_whatsapp.py`). There is nothing to configure. It adds no Guest permissions, and the hook does nothing when CRM is not installed or already has the fix.

Remove the hook when your CRM version includes frappe/crm#3214.

**Messages sent from the WhatsApp Business mobile app (Coexistence)**

In Coexistence mode Meta reports each message typed in the Business app as an `smb_message_echoes` webhook. `frappe_whatsapp` logs it but does not save it, so the message is missing from the CRM WhatsApp tab.

This app saves each echo as an outgoing `WhatsApp Message` (`whatsapp_standalone/echoes.py`, an `after_insert` hook on `WhatsApp Notification Log`). The message is not sent to Meta again. A one-time patch saves the echoes that are already in the log.

- Requirement: the Meta app must be subscribed to the `smb_message_echoes` webhook field.
- Supported: text messages and reactions.
- Not supported yet: media sent from the Business app, and the `history` sync of older chats.

### Tests

The tests use stub modules, so no site is needed:

```bash
env/bin/python -m unittest whatsapp_standalone.overrides.test_crm_whatsapp whatsapp_standalone.test_echoes
```
