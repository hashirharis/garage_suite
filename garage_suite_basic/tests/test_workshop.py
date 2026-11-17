from datetime import timedelta
from unittest.mock import patch
from odoo import Command, fields
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import tagged, new_test_user
from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged('post_install', '-at_install')
class TestWorkshopIntegration(AccountTestInvoicingCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manager = new_test_user(cls.env, login='gs_manager', groups='garage_core.group_garage_manager,account.group_account_manager')
        cls.technician = new_test_user(cls.env, login='gs_technician', groups='garage_core.group_garage_technician')
        cls.inspector = new_test_user(cls.env, login='gs_inspector', groups='garage_core.group_garage_quality')
        cls.reception = new_test_user(cls.env, login='gs_reception', groups='garage_core.group_garage_receptionist')
        cls.cashier = new_test_user(cls.env, login='gs_cashier', groups='garage_core.group_garage_cashier')
        cls.technician.sudo().write({'garage_hourly_cost': 30})
        cls.partner = cls.partner_a
        cls.partner.write({'is_garage_customer': True, 'garage_service_consent': True})
        cls.labour = cls.env['product.product'].create({'name': 'Garage Labour', 'type': 'service', 'list_price': 100, 'taxes_id': [Command.clear()], 'property_account_income_id': cls.company_data['default_account_revenue'].id})
        cls.part = cls.env['product.product'].create({'name': 'Garage Part', 'standard_price': 8, 'type': 'consu', 'list_price': 20, 'taxes_id': [Command.clear()], 'property_account_income_id': cls.company_data['default_account_revenue'].id})
        cls.vehicle = cls.env['garage.vehicle'].with_user(cls.manager).create({'customer_id': cls.partner.id, 'vin': 'INTEGRATIONVIN', 'make': 'Test', 'model': 'Test', 'service_interval_months': 6, 'service_interval_km': 10000})

    def new_job(self):
        job = self.env['garage.job.card'].with_user(self.manager).create({
            'customer_id': self.partner.id, 'vehicle_id': self.vehicle.id, 'odometer': 100, 'date': fields.Datetime.now(),
            'technician_ids': [Command.set(self.technician.ids)],
            'complaint_ids': [Command.create({'name': 'Engine noise'})],
            'line_ids': [Command.create({'name': 'Diagnosis and service', 'product_id': self.labour.id, 'planned_hours': 1, 'labour_charge': 100})],
        })
        job.action_generate_inspections()
        return job

    def sign(self, job, phase, user=None):
        user = user or (self.inspector if phase == 'final' else self.technician if phase == 'technical' else self.manager)
        inspection = job.inspection_ids.filtered(lambda i: i.phase == phase and i.work_revision == job.work_revision)
        self.assertEqual(len(inspection), 1)
        inspection = inspection.with_user(user)
        inspection.line_ids.write({'result': 'pass'})
        inspection.action_sign()
        return inspection

    def authorize(self, job):
        self.sign(job, 'reception')
        job.action_start_diagnosis()
        action = job.action_create_estimate()
        quote = self.env['sale.order'].with_user(self.manager).browse(action['res_id'])
        quote.write({'order_line': [Command.create({'product_id': self.part.id, 'product_uom_qty': 2, 'price_unit': 20, 'tax_ids': [Command.clear()]})]})
        quote.action_garage_issue()
        quote.write({'garage_approver_id': self.partner.id, 'garage_consent_channel': 'in_person', 'garage_consent_evidence': 'Signed customer consent held with the visit'})
        quote.action_garage_approve()
        return quote

    def ready_job(self):
        with patch('odoo.fields.Datetime.now', return_value=fields.Datetime.now() - timedelta(hours=2)):
            job = self.new_job()
            quote = self.authorize(job)
        self.sign(job, 'technical')
        job.with_user(self.technician).action_progress()
        move = self.env['garage.part.movement']
        for kind, qty, user in [('issue', 2, self.manager), ('consume', 1, self.technician), ('return', 1, self.manager)]:
            move.with_user(user).create({'job_id': job.id, 'product_id': self.part.id, 'kind': kind, 'quantity': qty, 'reason': 'Recorded service material movement'})
        now = fields.Datetime.now()
        self.env['garage.job.time.entry'].with_user(self.technician).create({'job_id': job.id, 'operation_line_id': job.line_ids.id, 'technician_id': self.technician.id, 'start': now - timedelta(hours=1), 'end': now})
        job.with_user(self.technician).write({'work_complete': True})
        job.with_user(self.technician).action_progress()
        with self.assertRaises(ValidationError):
            job.with_user(self.inspector).action_progress()
        self.sign(job, 'final')
        job.with_user(self.inspector).action_progress()
        self.assertEqual(job.state, 'ready')
        return job, quote

    def test_full_visit_consumption_invoice_partial_payment_release(self):
        job, quote = self.ready_job()
        action = job.with_user(self.cashier).action_create_invoice()
        invoice = self.env['account.move'].with_user(self.cashier).browse(action['res_id'])
        self.assertEqual(job.with_user(self.cashier).action_create_invoice()['res_id'], invoice.id)
        self.assertEqual(invoice.amount_total, 120)
        self.assertEqual(invoice.invoice_line_ids.filtered(lambda l: l.product_id == self.part).quantity, 1)
        invoice.action_post()
        self.sign(job, 'delivery')
        job.write({'delivery_recipient': self.partner.name, 'delivery_acknowledgment': 'Vehicle received with all documents'})
        with self.assertRaises(ValidationError):
            job.action_progress()
        bank = self.company_data['default_journal_bank']
        for amount in [40, 80]:
            wizard = self.env['account.payment.register'].with_user(self.cashier).with_context(active_model='account.move', active_ids=invoice.ids).create({'amount': amount, 'journal_id': bank.id, 'payment_date': fields.Date.today()})
            wizard._create_payments()
            if amount == 40:
                self.assertEqual(invoice.amount_residual, 80)
                with self.assertRaises(ValidationError):
                    job.action_progress()
        self.assertEqual(invoice.amount_residual, 0)
        finance = job.with_user(self.cashier).get_dashboard()['finance']
        self.assertEqual(next(m['value'] for m in finance if m['key'] == 'collected'), 120)
        job.action_progress()
        job.action_progress()
        self.assertEqual(job.state, 'closed')
        self.assertTrue(job.closed_at)
        self.assertEqual(self.env['garage.service.reminder'].with_user(self.manager).search_count([('job_id', '=', job.id)]), 1)

    def test_estimate_version_is_immutable_and_cannot_skip_consent(self):
        job = self.new_job()
        with self.assertRaises(ValidationError):
            job.write({'state': 'authorized'})
        quote = self.authorize(job)
        with self.assertRaises(ValidationError):
            quote.order_line[:1].write({'price_unit': 1})
        with self.assertRaises(ValidationError):
            quote.write({'partner_id': self.partner_b.id})
        with self.assertRaises(ValidationError):
            quote.write({'garage_consent_evidence': 'Changed evidence'})
        revision = self.env['sale.order'].with_user(self.manager).browse(job.action_create_estimate()['res_id'])
        self.assertEqual(revision.garage_version, quote.garage_version + 1)
        with self.assertRaises(ValidationError):
            job.with_user(self.technician).action_progress()
        self.assertEqual(quote.garage_consent, 'approved')

    def test_reception_and_unassigned_technician_cannot_authorize_work(self):
        job = self.new_job()
        with self.assertRaises(AccessError):
            job.with_user(self.reception).action_create_estimate()
        other = new_test_user(self.env, login='gs_other_technician', groups='garage_core.group_garage_technician')
        with self.assertRaises(AccessError):
            job.with_user(other).read(['name'])
        with self.assertRaises(AccessError):
            self.env['garage.service.type'].with_user(self.reception).create({'name': 'Unauthorized Master'})

    def test_appointment_and_crm_conversion_are_idempotent(self):
        now = fields.Datetime.now() + timedelta(days=1)
        appointment = self.env['garage.appointment'].with_user(self.reception).create({'customer_id': self.partner.id, 'vehicle_id': self.vehicle.id, 'start': now, 'end': now + timedelta(hours=1), 'complaint': 'Oil service', 'odometer': 100})
        appointment.action_arrived()
        first = appointment.action_convert()['res_id']
        self.assertEqual(first, appointment.action_convert()['res_id'])
        lead = self.env['crm.lead'].with_user(self.manager).create({'name': 'Service enquiry', 'partner_id': self.partner.id, 'garage_vehicle_id': self.vehicle.id})
        self.assertEqual(lead.action_garage_job()['res_id'], lead.action_garage_job()['res_id'])

    def test_rework_requires_fresh_quality_and_credit_release_is_audited(self):
        job, quote = self.ready_job()
        job.write({'exception_reason': 'Recheck repair after road test'})
        job.action_rework()
        self.assertEqual(job.work_revision, 1)
        job.action_generate_inspections()
        job.with_user(self.technician).write({'work_complete': True})
        job.with_user(self.technician).action_progress()
        with self.assertRaises(ValidationError):
            job.with_user(self.inspector).action_progress()
        self.sign(job, 'final')
        job.with_user(self.inspector).action_progress()
        invoice = self.env['account.move'].with_user(self.cashier).browse(job.with_user(self.cashier).action_create_invoice()['res_id'])
        invoice.action_post()
        with self.assertRaises(AccessError):
            job.write({'credit_release_by': self.manager.id})
        job.write({'credit_release_reason': 'Approved corporate credit terms'})
        job.action_credit_release()
        self.assertEqual(job.credit_release_by, self.manager)
        self.sign(job, 'delivery')
        job.write({'delivery_recipient': self.partner.name, 'delivery_acknowledgment': 'Corporate handover'})
        job.action_progress()
        self.assertEqual(job.state, 'delivered')
        self.assertEqual(invoice.amount_residual, 120)

    def test_print_reports_render(self):
        job = self.new_job()
        html, _ = self.env.ref('garage_basic_reports.job_print').with_user(self.manager)._render_qweb_html('garage_basic_reports.job_document', job.ids)
        self.assertIn(job.name.encode(), html)
        inspection = job.inspection_ids[:1]
        html, _ = self.env.ref('garage_basic_reports.inspection_print').with_user(self.manager)._render_qweb_html('garage_basic_reports.inspection_document', inspection.ids)
        self.assertIn(inspection.template_id.name.encode(), html)

    def test_cost_snapshots_and_financial_role_privacy(self):
        job, quote = self.ready_job()
        self.assertAlmostEqual(job.service_cost, 38)
        self.technician.sudo().write({'garage_hourly_cost': 50})
        self.part.write({'standard_price': 15})
        self.assertAlmostEqual(job.service_cost, 38)
        with self.assertRaises(AccessError):
            quote.with_user(self.technician).read(['amount_total'])
        with self.assertRaises(AccessError):
            job.part_movement_ids.with_user(self.technician).read(['unit_cost'])

    def test_credit_notes_preserve_invoice_and_require_manager(self):
        job, quote = self.ready_job()
        invoice = self.env['account.move'].with_user(self.cashier).browse(job.with_user(self.cashier).action_create_invoice()['res_id'])
        invoice.action_post()
        with self.assertRaises(AccessError):
            invoice.write({'garage_correction_reason': 'Unauthorized refund'})
        invoice = invoice.with_user(self.manager)
        invoice.write({'garage_correction_reason': 'Approved service correction'})
        credit = invoice._reverse_moves([{'date': fields.Date.today(), 'invoice_date': fields.Date.today()}])
        self.assertEqual(credit.garage_job_id, job)
        self.assertEqual(credit.reversed_entry_id, invoice)
        with self.assertRaises(AccessError):
            credit.with_user(self.cashier).action_post()
        credit.action_post()
        self.assertEqual(credit.state, 'posted')
        self.assertEqual(credit.garage_correction_reason, 'Approved service correction')

    def test_revision_retains_full_scope_and_cannot_remove_consumed_parts(self):
        job = self.new_job()
        quote = self.authorize(job)
        self.sign(job, 'technical')
        job.with_user(self.technician).action_progress()
        self.env['garage.part.movement'].with_user(self.manager).create({'job_id': job.id, 'product_id': self.part.id, 'kind': 'issue', 'quantity': 2, 'reason': 'Approved issue'})
        self.env['garage.part.movement'].with_user(self.technician).create({'job_id': job.id, 'product_id': self.part.id, 'kind': 'consume', 'quantity': 1, 'reason': 'Installed part'})
        revised = self.env['sale.order'].with_user(self.manager).browse(job.action_create_estimate()['res_id'])
        self.assertEqual(job.state, 'on_hold')
        self.assertEqual(revised.order_line.filtered(lambda l: l.product_id == self.part).product_uom_qty, 2)
        revised.order_line.filtered(lambda l: l.product_id == self.part).write({'product_uom_qty': 0})
        with self.assertRaises(ValidationError):
            revised.action_garage_issue()
        self.assertEqual(quote.garage_consent, 'approved')
