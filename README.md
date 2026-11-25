### WhatsApp Standalone

WhatsApp integration extensions for Frappe CRM: Business-app message sync (Coexistence), automatic leads from new WhatsApp numbers, Activity timeline rows, shared-mailbox email linking, and placing the WhatsApp tab after Activity.

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

**WhatsApp tab right after Activity on Leads and Deals**

By default Frappe CRM places the `WhatsApp` tab near the end of the Lead and Deal tab bar. This app injects a lightweight stylesheet (`whatsapp_standalone/public/css/crm_whatsapp_tab.css`) into `/crm` HTML responses via an `after_request` hook (`whatsapp_standalone/crm_ui.py`) so `WhatsApp` appears immediately after `Activity` on both Leads and Deals (desktop and mobile) without modifying upstream `crm`.

**Messages sent from the WhatsApp Business mobile app (Coexistence)**

In Coexistence mode Meta reports each message typed in the Business app as an `smb_message_echoes` webhook. `frappe_whatsapp` logs it but does not save it, so the message is missing from the CRM WhatsApp tab.

This app saves each echo as an outgoing `WhatsApp Message` (`whatsapp_standalone/echoes.py`, an `after_insert` hook on `WhatsApp Notification Log`). The message is not sent to Meta again. A one-time patch saves the echoes that are already in the log.

- Requirement: the Meta app must be subscribed to the `smb_message_echoes` webhook field.
- Supported: text messages and reactions.
- Not supported yet: media sent from the Business app, and the `history` sync of older chats.

**Leads from incoming messages**

The first message from a number that is not yet a CRM Lead or CRM Deal creates a `CRM Lead` (`whatsapp_standalone/incoming_leads.py`, an `after_insert` hook on `WhatsApp Message`).

- The lead gets the sender's WhatsApp profile name (HTML removed, cut to 140 characters; the number if there is no usable name), `mobile_no` as `+<digits>`, source `WhatsApp` and status `New`.
- The message is linked to the lead (or the existing lead or deal). CRM links a message when it validates it, which is before the lead of a new number exists; without this link the first message is missing from the WhatsApp tab.
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

Requirements: Frappe CRM is installed, and the `New` lead status and the `Sales Manager` role exist. Without CRM the hook does nothing. Install CRM before this app: the fixtures need the CRM doctypes, and a bench without CRM has not been tested.

The notification reaches the lead owner only if the lead already has an owner when it is created. A lead created from a message has none, so at first only the `Sales Manager` role is notified.

Remove this module and its hook when Frappe CRM creates leads from WhatsApp messages by itself.

**WhatsApp and shared-mailbox email in the Activity timeline**

*WhatsApp* (`whatsapp_standalone/activity_timeline.py`): the Activity tab of a Lead or Deal shows a row for each WhatsApp message, and the Emails tab does not. The module wraps CRM's `crm.api.activities.get_activities` (`override_whitelisted_methods`). CRM runs first, so its permission check applies. The rows are plain text entries, the kind the page draws for "created this lead", so they are not email cards.

- Incoming: `Kai +919535450135 messaged walue.ai on WhatsApp: Hello`.
- Outgoing, from CRM or the Business app: `<CRM user or account name> sent a WhatsApp message to +919535450135: …`.
- A reaction: `… reacted 😂 to a WhatsApp message`. A message without text shows its type, for example `[image]`.
- A deal also shows the messages of its lead. The newest 200 messages are read (`MESSAGE_LIMIT`). Text is plain, on one line, and cut at 300 characters.
- An error while adding the rows is written to the Error Log as "WhatsApp activity rows failed", and the page still gets CRM's own entries.
- Limits: the row has the lead icon and no reply buttons, so reply from the WhatsApp tab. A new message shows after the page is refreshed. Only one app can override this CRM method on a site; `custom_crm` overrides the same method, so do not install both on one site.
- A one-time patch (`patches/remove_whatsapp_timeline_entries.py`) deletes the email-style entries an earlier version of this app made.
- Meta does not send replies to a WhatsApp Status for numbers connected to Cloud API (Coexistence), so they cannot appear.

*Email* (`whatsapp_standalone/email_linking.py`, a `before_insert` hook on `Communication`): an email of any email account that is not linked yet is linked to a `CRM Lead` by address. For a received email the sender is matched; for a sent one the recipients and cc.

- It links only when exactly one lead has such an address. With no match, or two leads on one address, the email stays unlinked.
- It runs before CRM's own handler, so CRM sees a linked email and does not create a second lead.
- Failures are written to the Error Log as "Email lead link failed"; mail is still saved.
- Limit: leads only. A deal's contact address is not matched, and mail that came in before this app was updated is not linked.

Remove the email module and its hook if CRM links shared-mailbox mail to leads by itself, and the activity module and its override if CRM shows WhatsApp in the timeline by itself.

### Tests

The tests use stub modules, so no site is needed. Run them from the bench directory (the folder that holds `apps/` and `env/`):

```bash
env/bin/python -m unittest whatsapp_standalone.test_crm_ui whatsapp_standalone.test_echoes whatsapp_standalone.test_incoming_leads whatsapp_standalone.test_email_linking whatsapp_standalone.test_activity_timeline whatsapp_standalone.patches.test_remove_whatsapp_timeline_entries whatsapp_standalone.test_fixtures
```
