### WhatsApp Standalone

WhatsApp integration fixes and extensions for Frappe CRM: incoming-reply fix, Business-app message sync (Coexistence) and automatic leads from new WhatsApp numbers

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

**Leads from incoming messages**

The first message from a number that is not yet a CRM Lead or CRM Deal creates a `CRM Lead` (`whatsapp_standalone/incoming_leads.py`, an `after_insert` hook on `WhatsApp Message`).

- The lead gets the sender's WhatsApp profile name (HTML removed, cut to 140 characters; the number if there is no usable name), `mobile_no` as `+<digits>`, source `WhatsApp` and status `New`.
- A number is matched against `mobile_no` and `phone` of every Lead and Deal, ignoring spaces and the characters `+ - ( ) .`. A match means no new lead.
- A Redis lock per number makes the check and the insert one step. It is held until the request transaction commits, so two messages that arrive together cannot create two leads. A second message waits at most 2 seconds for the lock; if it cannot get it, it is logged and skipped.
- A failure is rolled back and written to the Error Log as "WhatsApp lead create failed". The webhook still succeeds, so Meta does not retry.
- Messages saved as `Outgoing`, including Business-app echoes, never create a lead.
- Limit: a number is matched as a full digit string. A stored number without its country code is not matched.
- To change the source or the status, edit `LEAD_SOURCE` and `LEAD_STATUS` in `incoming_leads.py`. Keep `LEAD_SOURCE` equal to the source in the fixtures below.

Records shipped with the app (`whatsapp_standalone/fixtures/`):

- A `CRM Lead Source` named `WhatsApp`.
- A system `Notification` named `New WhatsApp Lead`. It fires when a `CRM Lead` is created with source `WhatsApp`, and goes to the `Sales Manager` role and the lead owner.

Frappe imports fixtures on `bench install-app` and again on every `bench migrate`. A change made to these two records in the UI is replaced by the next migrate. Edit the fixture files instead, or run `bench export-fixtures` after a UI change.

Requirements: Frappe CRM is installed, and the `New` lead status and the `Sales Manager` role exist. If CRM is not installed, Frappe skips the fixtures and the hook does nothing.

The notification reaches the lead owner only if the lead already has an owner when it is created. A lead created from a message has none, so at first only the `Sales Manager` role is notified.

Remove this module and its hook when Frappe CRM creates leads from WhatsApp messages by itself.

### Tests

The tests use stub modules, so no site is needed. Run them from the bench directory (the folder that holds `apps/` and `env/`):

```bash
env/bin/python -m unittest whatsapp_standalone.overrides.test_crm_whatsapp whatsapp_standalone.test_echoes whatsapp_standalone.test_incoming_leads whatsapp_standalone.test_fixtures
```
