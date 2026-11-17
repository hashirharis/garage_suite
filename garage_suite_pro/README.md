# Garage Suite Pro for Odoo 19

Install `garage_suite_pro` on a staging copy of an up-to-date Garage Suite Basic
database. Pro extends the existing customer, vehicle, job, quotation, invoice
and payment models. The existing Garage launcher becomes **Garage Suite Pro**
and opens the Pro overview and role-specific navigation. Existing Garage
reports and master configuration are available from the Pro menu. Pro uses standard Odoo applications for Stock, Purchase,
Sales, POS, Accounting, HR, Attendance, Time Off, Expenses, Maintenance and
Email Marketing. Country-specific accounting remains configured through the
appropriate Odoo localization and Garage country addon.

To enable the optional website shop and customer visit history, upgrade
`suite_theme` with the Website compatibility change, then install
`garage_pro_online`. Publish the intended parts in Website and configure the
store's delivery, payment and tax settings. Customers sign into the portal to
see visits that were recorded for their account and the website's company.

## Workshop setup

1. Set the companies or native Odoo branches the team is allowed to use.
   Configure each branch's warehouse, journals, product availability and
   employee assignments under its operating company. Use native stock
   transfers and receipts between correctly configured sites.
2. Assign **Workshop Planner**, **Workshop Inventory**, **Garage Buyer**,
   **Garage Purchase Approver**, **Claims and Contracts Manager**, or
   **Garage Executive Analytics** under Settings. **Garage Pro Operations
   Manager** includes the Garage operational roles, planning, workshop stock,
   claims and executive reporting. Purchasing approvals, Accounting and HR
   permissions still require their separate roles.
3. Link each technician's Odoo user to their HR employee. Configure working
   hours, time off, and Garage skills. Assign the technician on the job card
   before creating a task. Schedule prerequisite tasks before their successors.
   A technician can progress their own assigned tasks. Jobs with active tasks
   must resolve them before Quality Check.
4. Flag automotive goods as **Workshop Part / Consumable**, add their
   references and catalogue-backed fitment, and configure native price lists,
   supplier references, and replenishment rules as needed.
5. To enable workshop stock, set the warehouse, a separate internal staging
   location and a production consumption location on the company. Use distinct
   locations outside the warehouse stock subtree for staging. The first
   reservation reserves the native stock move. Issue it from the job's Parts
   Movements register, then consume or return the issued quantities.
   Configuration applies to new stock movements. Reconcile existing open
   material in staging before enabling integration, since older Basic evidence
   has no corresponding warehouse movement.
6. On shortages, submit a purchase request. A different purchase approver
   approves it, the buyer prepares a quote per supplier, and the approver
   awards the selected request-linked quote. Receive using Odoo's normal
   inspection, backorder and return processes. A linked vendor bill for a
   stock-managed part cannot post above the net quantity received.
7. For insured work, record the assessment, estimate revision, allocations and
   surveyor approval. The current estimate needs surveyor approval before an
   insured job is started or resumed. Customer consent still applies. For
   contracts, approve entitlement before authorizing covered work, and record
   consumption against the closed job. Process billable scope in Accounting.

## Interpreting the reports

- **Workshop profitability** groups ready, delivered and closed jobs by
  company, advisor and reception date. Revenue is posted untaxed service
  revenue net of credit notes. Direct cost is recorded labour plus consumed
  parts at the Garage cost snapshot. It excludes overhead and is distinct
  from the accounting profit and loss statement.
- **Technician labour contribution** allocates posted net labour revenue for
  each job and labour product in proportion to completed hours. Subtracts
  snapshotted time costs. Parts and packages, jobs with no logged labour for
  that product, overhead, and cash collections are outside the allocation.
  Open an allocation row to identify its underlying job and technician.
- **Employee capacity** compares scheduled task hours and completed time
  entries with the employee's working calendar after approved leave. The
  productivity percentage uses actual logged hours over available hours.
  With no available hours, the percentage is omitted.
- **Schedule variance** compares task reservation duration with linked time
  entries using planned start date. A time entry should explicitly identify
  the task for attribution. **Contract contribution** uses agreement value
  less recorded direct cost on consumed visits, independent of payment.
- **Insurance exposure** tracks approved insurer balances and verified
  settlements. Native Sales, POS, Purchasing, Inventory and Accounting
  retain their own measures and reports. Select one currency when comparing
  totals. Different company currencies are not converted in the Garage pivots.

## SRS coverage boundaries

Workshop inventory integration currently supports untracked, stock-managed
parts. Native receipts, transfers, counts and retail track lots and serials.
Garage-specific lot selection, VIN-range data, substitution approval, a
custom branch-transfer discrepancy queue, and global negative-stock policy
remain separate work.

The claims and entitlement workflows record approval and allocation. They do
not replace the Basic workshop invoice payer rule. Insurer/customer split
invoices, partial insurer settlement matching, automatic contract
bill-through, and insurer gateway integrations remain separate work.
Purchase awards add receipt-quantity matching for linked stock items.
Supplier rebate automation, supplier self-service and negotiated variance
thresholds are separate.

The Online addon provides signed-in customer visit tracking and uses native
Website Sale. Garage-specific portal bookings, portal approval links, mobile
apps and offline synchronization, provider-specific WhatsApp/SMS/payment APIs,
commercial license enforcement and optional AI need additional implementation
or approved provider contracts. Native Accounting reports available to a user
depend on the deployed Odoo edition and installed localizations.

## Demo dashboard

Install the optional [Garage Suite Pro Demo Data addon](../garage_demo_pro/README.md)
in a training database and select **Garage Pro Demo**. The management
dashboard shows current-company workshop performance and the rolling monthly
profitability chart for users with executive analytics access. Clicking a
profit figure or month opens the profitability pivot with the matching
company, visit cohort and date filters.
