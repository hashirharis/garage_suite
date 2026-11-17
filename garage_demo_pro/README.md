# Garage Suite Pro demo data

Install `garage_demo_pro` in a demo or training database. In Apps, update the
app list and clear the default **Apps** filter to find this technical addon.
It creates **Garage Pro Demo**, a separate synthetic company using the India
localization and INR. It can coexist with the country-specific Basic demo packs.
The post-install hook runs even when the optional Odoo demo flag is disabled.

Grant a test user access to the demo company, select it as the current company,
and assign **Garage Pro Operations Manager** or **Garage Executive Analytics** to
see the profitability scorecard and monthly comparison. Add **Garage Buyer** to
see the purchasing queue and **Workshop Planner** to see the planning queue.
The synthetic staff accounts have no demo login credentials configured.

The dataset spans 13 completed months plus recent and upcoming activity. It
contains varied service outcomes, posted invoices and receipts, attributable
technician hours and dependent tasks, parts stock and fitment, retail deliveries,
purchase requests and receipts, insurer exposures, and service contracts.
Use **All time** to compare the full workshop history. The profitability chart
always displays the last 12 calendar months, including the current month.

The addon seeds once and leaves the synthetic business records available after
uninstall. Start with a fresh training database to regenerate the demo.
