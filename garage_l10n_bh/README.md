# Bahrain tax integration

Optional country adapter depending on Odoo 19's `l10n_bh` and Garage billing.
Install only where needed. Configure the intended company's country, chart of
accounts, fiscal positions, journals, taxes and tax IDs using Odoo Accounting.
This adapter does not change other companies or install its own tax rates.
Standard Garage estimates and invoices retain Odoo's native tax calculations,
rounding, invoice numbering and country-specific invoice/report extensions.
Electronic-invoicing gateways, credentials, statutory filing and certification
are separate deployment requirements; this module does not claim to implement them.
