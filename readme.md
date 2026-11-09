# Garage Suite

Garage Suite is a planned modular Garage Management ERP for Odoo 19. It is designed for independent garages, multi-brand workshops, motorcycle service centres, spare parts businesses and automotive service chains.

The product covers the vehicle service lifecycle from appointment and reception through inspection, estimate approval, repair, quality control, invoicing, delivery and service reminders.

## Project status

This directory currently contains the requirements specification. Installable Odoo modules, application code and automated tests have not yet been added. Features described here represent the proposed product scope.

## Editions

| Edition | Planned scope |
| --- | --- |
| Garage Suite Basic | Customers, vehicles, appointments, job cards, inspections, labour, estimates, parts consumption, service billing, payment tracking, reminders and operational reports. |
| Garage Suite Pro | All Basic capabilities plus automotive parts catalogues, advanced inventory, purchasing, retail and wholesale sales, POS, accounting, CRM, insurance, warranty and AMC, fleet operations, branches, analytics and mobile applications. |

Basic and Pro are intended to share core models and a common codebase. Upgrading to Pro should extend the existing installation while preserving customers, vehicles, service history and transaction references.

Optional capabilities and dependency conditions are defined in the SRS.

## Documentation

Start with the [Software Requirements Specification](docs/srs.md). It includes:

- Product scope and Basic versus Pro edition boundaries.
- User roles, responsibilities and approval permissions.
- Functional requirements with stable identifiers.
- Ten detailed workflow charts covering reception, service execution, estimates, parts, procurement, billing, offline synchronization, branch transfers, contracts and edition upgrades.
- Job states, business rules and approval controls.
- Logical data relationships and module architecture diagrams.
- Integration and nonfunctional requirements.
- Acceptance scenarios, release planning and decisions requiring stakeholder review.
- A detailed feature catalogue and proposed Odoo module structure.

The diagrams use Mermaid. Open the SRS in a Markdown viewer with Mermaid support to see rendered charts.

## Directory structure

```text
garage_suite/
├── readme.md        # Project overview and documentation entry point
└── docs/
    └── srs.md       # Software Requirements Specification
```

## Proposed technical foundation

- **ERP platform:** Odoo 19.
- **Backend:** Python and the Odoo ORM.
- **Database:** PostgreSQL.
- **Web interface:** Odoo web client, OWL, JavaScript and XML.
- **Reporting:** Odoo reports, QWeb PDFs and exports.
- **Mobile:** Proposed Flutter applications using secured backend APIs.

The Odoo Community or Enterprise foundation, accounting dependencies, external providers and deployment configuration remain subject to architecture and stakeholder review.

## Development approach

1. Review the SRS and resolve the decisions listed in its delivery and approval section.
2. Define module dependencies, models, views, security and integration contracts.
3. Implement the Basic workshop lifecycle and its approval, quality and billing controls.
4. Extend the shared foundation with Pro inventory, trading, finance and enterprise capabilities.
5. Add mobile experiences and integrations with server-side authorization and controlled synchronization.
6. Validate acceptance scenarios, access isolation, reconciliation, upgrades and recovery before release.

Installation and test commands will be documented when the corresponding modules and development environment are available.
