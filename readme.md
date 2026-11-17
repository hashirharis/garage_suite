# Garage Suite for Odoo 19

Garage Suite Basic composes shared workshop modules with standard Odoo CRM,
Sales, Invoicing and Payments. Pro can extend these same records and identifiers.
The requirements baseline is [docs/srs.md](docs/srs.md); current coverage and
remaining scope are recorded in [docs/implementation-status.md](docs/implementation-status.md).

## Modules

| Addon | Responsibility |
| --- | --- |
| `garage_core` | Standard customers, vehicle identity/ownership history, job headers, roles and sequences |
| `garage_service_master` | Vehicle makes/models/variants/categories; service types/categories, bays, skills, labour rates, operations, packages and product references |
| `garage_workshop` | Appointments, versioned Sales estimates, manual consent, inspections, time entries, parts issue/consumption/returns, delivery and reminders |
| `garage_service_billing` | Consumption-based customer invoices, payment release gate, manager credit release, credit-note traceability and cost/margin snapshots |
| `garage_crm` | Standard opportunities linked to customers, vehicles and idempotent job creation |
| `garage_basic_reports` | Operational pivots/graphs/registers and printable job/inspection reports |
| `garage_suite_basic` | Installation application, shared theme dependency and live workshop dashboard |
| `garage_l10n_bh` | Optional Bahrain adapter depending on native `l10n_bh` |
| `garage_l10n_sa` | Optional Saudi Arabia adapter depending on native `l10n_sa` |
| `garage_l10n_ae` | Optional UAE adapter depending on native `l10n_ae` |
| `garage_l10n_in` | Optional India adapter depending on native `l10n_in` |

The four country adapters are independent: install the ones needed for your
companies. They expose country-specific tax configuration and retain native
localization behavior. They do not automatically switch a live company's chart,
activate all rates, register tax IDs or configure electronic-invoicing gateways.
Configure each company's country, chart, fiscal positions, taxes, journals and
payment methods through standard Accounting settings before invoicing.

## Install or upgrade

Odoo must see this directory, its parent `custom-addons` directory containing
`suite_theme`, and the shared `addons` directory containing MuK theme dependencies:

```bash
odoo -d YOUR_DATABASE --addons-path=/path/to/odoo/addons,/path/to/custom-addons,/path/to/custom-addons/garage_suite,/path/to/shared-addons -i garage_suite_basic --stop-after-init
```

For example, add `-i garage_l10n_in` to install the India adapter. Country modules
are optional and are not dependencies of Basic. Back up the database and filestore
before deployment. Restart the server, update the Apps list and upgrade
`garage_suite_basic` plus the installed Garage feature modules when upgrading.
Existing customer/vehicle/job IDs are retained. First installation of the master
addon backfills structured make/model/variant records from existing vehicle text;
legacy labels remain available and new master links enforce consistency.

When moving from the original foundation, deploy the updated addon files and
restart Odoo before retrying **Upgrade** on Garage Suite Basic. The first
installation of Service Masters loads the missing Core roles and access data
before importing its own access rules. Existing advisor and manager assignments
keep their original external IDs. For a command-line upgrade, use
`-u garage_core,garage_suite_basic --stop-after-init` with the same database and
addons path.

## Roles

Assign roles explicitly under Settings → Users. A technical administrator is not
automatically an operational Garage Manager. The original `group_garage_user`
remains a compatible advisor grant; use the clearly named roles for new users.

| Role | Access |
| --- | --- |
| Workshop Reader | Permitted company records and operational reports, without transaction writes |
| Receptionist | Customer/vehicle registration, appointment booking and job reception; cannot approve estimates |
| Service Advisor | Reception plus diagnosis, quote preparation, recording evidenced customer consent, assignment and delivery coordination |
| Technician | Assigned jobs, technical inspection, own labour time and authorized parts consumption |
| Quality Inspector | Final inspection sign-off and readiness; assigned technicians cannot sign their own final QC |
| Parts Storekeeper | Authorized issues and unused-part returns |
| Service Cashier | Standard invoicing/payment permissions plus guarded Garage invoice creation |
| Garage Manager | Operational roles, master maintenance, controlled identity/ownership changes, discounts above advisor limits, exceptions and credit releases |
| Garage Owner / Reporting | Operational and standard accounting read access; cost and margin reports |
| System Administrator | Technical users, company settings and localization configuration; grant operational roles separately |

Standard Sales/Accounting permissions remain applicable to their native records.
Garage roles do not replace those applications' security models. Technicians do
not receive quote or invoice access. Private scope checks verify approved work
without exposing commercial documents. Company rules cover all new records.

## Configuration and daily flow

Use **Garage Suite Basic → Configuration** for vehicle and service masters,
inspection templates, products/parts, staff/skills and billing configuration.
System administrators can configure company-specific estimate validity, advisor
discount limits and expiry reminder lead times under **Garage Policies**.
Financial configuration requires the corresponding standard Accounting grant.

1. Register an individual/company customer and its vehicle. Registration and
   VIN/chassis remain separate; normalized duplicate checks apply per company.
2. Create a walk-in visit, or mark an appointment arrived and convert it, or
   convert a CRM enquiry. Retrying either conversion returns the existing visit.
3. Select/generate the inspection templates, complete reception checks and begin
   diagnosis. Configure service operations and package inclusions; packages must
   not be charged again as separate included labour.
4. Prepare an estimate. Add parts directly as standard Sales lines. Issue the
   version, record the customer/contact, channel and evidence, then record consent.
   Issued lines and approved evidence are immutable. A revision creates another
   version of the complete scope; work pauses for fresh consent on scope changes.
5. Assign technicians, complete technical inspection and start approved work.
   Record nonoverlapping time and append-only parts movements in product base UoM.
   These movements are a workshop ledger, not warehouse stock transactions.
6. Complete work, reconcile parts, and submit for independent final QC. Failed or
   missing mandatory checks block readiness. Rework requires a manager reason
   and a fresh inspection revision; earlier evidence remains intact.
7. Create the service invoice from the ready job. Labour uses approved pricing;
   parts bill actual consumption. Posting rechecks the source scope. Repeated
   invoice creation opens the existing invoice. Post and register partial/split
   payments using standard Odoo payment registration.
8. Complete delivery checks, recipient and acknowledgment. Unpaid invoices block
   release unless a manager records a reasoned credit release. Close after delivery;
   configured intervals create the next-service follow-up. Ownership changes do
   not alter historical customers or invoice payers.

Cancellation retains reason, actor and time. Visits with unreconciled execution
records cannot simply be cancelled. Reopening and rework retain manager reasons.
Reminder automation creates internal activities; it does not dispatch messages to
external gateways. Manual follow-up checks current ownership and customer consent.

## Reports

The Reports menu includes workshop performance/daily service, job registers,
appointment/no-show analysis, planned labour and actual technician time,
parts issues/consumption/returns, estimate approval pipeline, service follow-ups
and feedback, customer/vehicle histories and service frequency, service revenue,
outstanding invoices, daily customer collections and service cost/margin.
Pivots and graphs support native Odoo grouping, filters and exports; collections
are restricted to payments linked to Garage invoices. Financial and margin reports
require the corresponding roles. Cost snapshots use configured technician hourly
costs and product costs; they are operational estimates, not inventory valuation.

Print Job Card and Inspection Report from the records' Print menus. Estimate,
invoice, credit-note and payment-receipt output uses standard Odoo reports and any
installed native localization extensions.

### Dashboard and report exports

The dashboard opens role-specific workspaces for front desk, service advisors,
technicians, quality inspectors, parts storekeepers, billing, and management.
Users with several operational roles can switch between their workspaces.
Select a workload card, pipeline stage, or day on the reception chart to open
the source records. The seven-day reception chart uses local calendar dates.
Billing amounts use the active company's currency.

Open **Reports → Export PDF or Excel**, or use **Export reports** on the dashboard.
Choose a report and an optional date range. Both formats include the report's
underlying rows and respect company access and record rules. Excel exports
include filterable column headers and numeric amounts. PDF exports use the
company letterhead and landscape paper. PDF accepts up to 500 rows per export
and Excel up to 20,000. Use a narrower date range for larger registers.
Existing pivot tools remain available for grouped summaries.

For this interface update on an existing database, upgrade both
`garage_basic_reports` and `garage_suite_basic` together. On the command line,
use `-u garage_basic_reports,garage_suite_basic --stop-after-init` with the
database and addons path used above.

## Validation

Run the isolated integration suite (temporary PostgreSQL; dedicated filestore):

```bash
docker compose -p garage-basic-test -f compose.test.yml up --abort-on-container-exit --exit-code-from odoo
docker compose -p garage-basic-test -f compose.test.yml down --remove-orphans -v
```

Tests cover identities, roles/company isolation, conversion retries, immutable
consent, assigned work, material reconciliation, costing privacy, QC/rework,
invoice idempotency, partial payments, release gates, refunds and report rendering.
Country adapters are additionally installed together in a disposable localization
database; each country's native tax/chart configuration is tested in its own company.

The shared `suite_theme` remains outside this repository at `../suite_theme`.
The former `retail_suite_theme` is a compatibility bridge; its rename migration
preserves existing preferences and inherited view IDs. Framework identifiers,
third-party licenses and historical user content are retained.

## Localized workshop demo data

In a demo or training database, open Apps, refresh the apps list, clear the
default **Apps** filter, and search for a country pack by its technical name.
Each pack installs its matching Garage tax addon and seeds a dedicated
**Garage Demo** company with the native chart of accounts and local currency.

| Country | Demo addon | Tax addon |
| --- | --- | --- |
| Bahrain | `garage_demo_bh` | `garage_l10n_bh` |
| Saudi Arabia | `garage_demo_sa` | `garage_l10n_sa` |
| United Arab Emirates | `garage_demo_ae` | `garage_l10n_ae` |
| India | `garage_demo_in` | `garage_l10n_in` |

Each company has four synthetic customers and vehicles with linked make, model,
variant and category masters. The data covers 13 completed calendar months plus
a recent and upcoming work queue relative to installation. It includes repeat
visits, CRM opportunities, appointments, inspections, estimates, technician time,
parts usage, follow-ups, invoices, full and partial payments, unpaid balances,
and vehicles awaiting delivery.

Grant your test user access to the demo company and the Garage role you want to
exercise, then select that company. In **Garage → Reports**, choose dates covering
the preceding 13 months for the PDF and Excel exports. The generated staff records
are for assignment and workflow history and have no configured credentials.

The seed runs once per country on addon installation, including when Odoo's
optional demo flag is off. Upgrading or reinstalling a pack does not generate a
second dataset. The sample companies and their accounting entries persist after
uninstall, so use a disposable database for a clean reset.
