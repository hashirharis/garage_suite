# Run in Odoo shell against a disposable DB with all four demo packs installed.
from datetime import timedelta

from odoo import fields
from odoo.addons.garage_basic_reports.models.export import REPORTS
from odoo.addons.garage_demo_common.seed import seed_workshop

for code, currency in [('bh', 'BHD'), ('sa', 'SAR'), ('ae', 'AED'), ('in', 'INR')]:
    company_id = int(env['ir.config_parameter'].get_param('garage_demo.seeded_company_' + code))
    company = env['res.company'].browse(company_id).exists()
    assert company.country_id.code == code.upper() and company.currency_id.name == currency
    manager = env['res.users'].search([
        ('login', '=', f'garage-demo-{code}-manager@example.invalid'),
    ])
    scoped = env(user=manager.id, su=False, context={'allowed_company_ids': company.ids, 'tz': manager.tz})
    jobs = scoped['garage.job.card'].search([], order='date')
    assert len(jobs) == 55 and len(jobs.vehicle_id) == 4, (code, len(jobs))
    assert jobs[-1].date - jobs[0].date >= timedelta(days=365)
    assert all(vehicle.model_id and vehicle.variant_id for vehicle in jobs.vehicle_id)
    assert {'closed', 'ready', 'awaiting_approval', 'on_hold', 'cancelled'} <= set(jobs.mapped('state'))
    assert scoped['garage.job.card'].get_dashboard('all')['total'] == len(jobs)

    invoices = scoped['account.move'].search([('garage_job_id', 'in', jobs.ids)])
    assert len(invoices) == 52 and all(invoice.state == 'posted' for invoice in invoices)
    assert invoices.filtered(lambda invoice: invoice.amount_tax > 0), f'{code}: expected taxed invoices'
    assert invoices.filtered(lambda invoice: invoice.amount_residual == 0)
    assert invoices.filtered(lambda invoice: 0 < invoice.amount_residual < invoice.amount_total)
    assert invoices.filtered(lambda invoice: invoice.amount_residual == invoice.amount_total)

    counts = {}
    for key in REPORTS:
        wizard = scoped['garage.report.export'].create({
            'report_key': key,
            'date_from': jobs[0].date.date(),
            'date_to': fields.Date.context_today(manager),
        })
        _, _, rows = wizard._report_data(limit=5000)
        assert rows, f'{code}: report {key} is empty'
        assert wizard.action_pdf()['report_name'] == 'garage_basic_reports.export_pdf'
        html, _ = scoped.ref('garage_basic_reports.action_export_pdf')._render_qweb_html(
            'garage_basic_reports.export_pdf', wizard.ids,
        )
        assert b'<table' in html
        wizard.action_excel()
        assert wizard.file_data and wizard.file_name == key + '.xlsx'
        counts[key] = len(rows)
    seed_workshop(env, code)
    assert scoped['garage.job.card'].search_count([]) == len(jobs), f'{code}: duplicate seed'
    print(code.upper(), counts)
