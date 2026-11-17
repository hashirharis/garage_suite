# Basic implementation coverage

This is an implementation increment, not a claim that every acceptance condition
in the full SRS is release-certified. The core visit-to-payment path, configurable
masters, CRM integration, operational reporting and optional country localization
composition are implemented. Validate a deployment using its actual fiscal setup,
roles, opening data and operating procedures before production use.

| SRS area | Current implementation |
| --- | --- |
| FR-B01 Customers | Native partners, companies/contacts, customer vehicles/jobs/estimates, restricted invoice history and name/phone/email/VAT/registration/VIN search; native tax-ID duplicate warnings |
| FR-B02 Vehicles | Separate normalized registration/VIN, immutable identity/ownership events, structured specifications, visit odometer history and controlled lower readings |
| FR-B03 Appointments | Calendar, bay-overlap validation, arrival, reasoned rescheduling, cancelled/no-show states and idempotent conversion; advanced technician resource planning remains future work |
| FR-B04 Job cards | Canonical stages, complaints, diagnosis, assignments, consent gates, holds, rework revision, QC, settlement-aware handover and closure |
| FR-B05 Inspections | Configurable phase templates, mandatory snapshots, results/remarks/photos, role-controlled immutable sign-off and printable reports |
| FR-B06 Catalogue/labour | Categories, types, operations, fixed/hourly pricing, vehicle rates, packages, skills, planned/actual time and cost snapshots |
| FR-B07 Parts | Native parts products and base UoM; separately recorded issue, consumption and return quantities; warehouse stock remains an optional future addon |
| FR-B08 Estimates | Standard Sales pricing/taxes/discounts, versioned complete scope, expiry, manual approval/rejection evidence and immutable issued lines; secure portal/WhatsApp consent remains optional future work |
| FR-B09 Billing | Standard invoices, tax computation, partial/split payment registration, receipts, residual balances, controlled credit notes, immutable source links and release gates |
| FR-B10 Follow-ups | Next service date/km, document expiry follow-ups, consent/channel preferences, feedback and internal activities; email/SMS/WhatsApp gateway dispatch is not implemented |
| FR-B11 Reports | Operational dashboard, registers, grouped history/frequency, labour/time, parts, approvals, revenue, outstanding invoices, collections, feedback and operational margin |
| CRM (requested addition) | Standard opportunities with service type/vehicle linkage and idempotent visit creation |
| Country addons (requested addition) | Independent Bahrain, Saudi Arabia, UAE and India wrappers over the corresponding native Odoo localizations; statutory gateway certification/filing is outside these adapters |

The roadmap still includes optional portal/mobile consent, external communications,
optional stock, advanced resource scheduling, richer customer duplicate resolution,
configuration migration tooling for country changes, and production-level coverage
of every SRS exception scenario. Parts compatibility, procurement, branch management,
full enterprise accounting/reporting and warranty/AMC claims remain Pro scope.

The new modules extend the same shared records. Basic does not create a second
customer/vehicle/job database to be migrated when Pro is installed.

## Deployment checks

The four localization addons are optional composition adapters, not alternative
Garage billing engines. The tax/chart test loads each native country chart in its
own synthetic company and checks native sales taxes (including inactive templates),
a sales journal and the expected currency. The helper script refuses non-test
database names. Configure a real company's applicable tax registrations and rates
through its native localization; no single tax rate is assumed by Garage.

The dashboard now includes today's receipts, work in progress, readiness,
awaiting approvals, parts holds and repeat/rework counts, plus current-company
financial KPIs for authorized finance roles. Actual technician hours are reported;
a utilization percentage still needs configured working calendars and is not
invented from elapsed hours alone.
