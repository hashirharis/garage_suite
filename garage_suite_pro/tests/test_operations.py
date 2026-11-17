from datetime import datetime, time, timedelta, timezone

from odoo import Command, fields
from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import new_test_user, tagged


@tagged('post_install', '-at_install')
class TestProOperations(AccountTestInvoicingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manager = new_test_user(cls.env, login='garage_pro_manager', groups='garage_suite_pro.group_garage_pro_manager')
        cls.technician = new_test_user(cls.env, login='garage_pro_tech', groups='garage_core.group_garage_technician')
        cls.unassigned = new_test_user(cls.env, login='garage_pro_unassigned', groups='garage_core.group_garage_technician')
        cls.buyer = new_test_user(cls.env, login='garage_pro_buyer', groups='garage_suite_pro.group_garage_buyer')
        cls.approver = new_test_user(cls.env, login='garage_pro_purchase_approver', groups='garage_suite_pro.group_garage_purchase_approver')
        cls.employee = cls.env['hr.employee'].sudo().create({'name': 'Workshop Employee', 'user_id': cls.technician.id, 'company_id': cls.env.company.id})
        cls.vehicle = cls.env['garage.vehicle'].with_user(cls.manager).create({
            'customer_id': cls.partner_a.id, 'vin': 'PRO-TEST-VEHICLE', 'make': 'Test', 'model': 'Test',
        })
        cls.part = cls.env['product.product'].create({
            'name': 'Test service filter', 'type': 'consu', 'is_storable': True, 'garage_part': True,
            'list_price': 20, 'standard_price': 8, 'taxes_id': [Command.clear()],
        })

    def _job(self):
        return self.env['garage.job.card'].with_user(self.manager).create({
            'vehicle_id': self.vehicle.id, 'customer_id': self.partner_a.id, 'odometer': 100,
            'technician_ids': [Command.set(self.technician.ids)],
            'complaint_ids': [Command.create({'name': 'Replace filter'})],
        })

    def _sign(self, job, phase):
        inspection = job.inspection_ids.filtered(lambda item: item.phase == phase)
        inspection.line_ids.write({'result': 'pass'})
        inspection.action_sign()

    def _authorize(self, job):
        job.action_generate_inspections()
        self._sign(job, 'reception')
        job.action_start_diagnosis()
        order = self.env['sale.order'].with_user(self.manager).browse(job.action_create_estimate()['res_id'])
        order.order_line = [Command.create({'product_id': self.part.id, 'product_uom_qty': 2, 'price_unit': 20})]
        order.action_garage_issue()
        order.write({
            'garage_approver_id': self.partner_a.id, 'garage_consent_channel': 'in_person',
            'garage_consent_evidence': 'Customer signed scope',
        })
        order.action_garage_approve()
        self._sign(job, 'technical')
        job.action_progress()
        return order

    def test_task_dependencies_and_assignee_access(self):
        job = self._job()
        self._authorize(job)
        now = datetime.combine(fields.Date.today(), time.min, tzinfo=timezone.utc)
        intervals = self.employee.sudo().resource_calendar_id._work_intervals_batch(
            now, now + timedelta(days=8), resources=self.employee.sudo().resource_id,
        )[self.employee.sudo().resource_id.id]
        start = next(begin for begin, end, _resource in intervals if end - begin >= timedelta(hours=3))
        start = start.astimezone(timezone.utc).replace(tzinfo=None)
        model = self.env['garage.workshop.task'].with_user(self.manager)
        common = {'job_id': job.id, 'employee_id': self.employee.id}
        first = model.create({**common, 'name': 'Inspect', 'planned_start': start, 'planned_end': start + timedelta(hours=1)})
        second = model.create({
            **common, 'name': 'Replace', 'planned_start': start + timedelta(hours=1),
            'planned_end': start + timedelta(hours=2), 'predecessor_ids': [Command.link(first.id)],
        })
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            first.predecessor_ids = [Command.link(second.id)]
        first.action_schedule()
        second.action_schedule()
        overlap = model.create({**common, 'name': 'Overlap', 'planned_start': start, 'planned_end': start + timedelta(hours=1)})
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            overlap.action_schedule()
        self.assertFalse(model.with_user(self.unassigned).search([('id', '=', first.id)]))
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            second.with_user(self.technician).action_start()
        job.work_complete = True
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            job.action_progress()
        first.with_user(self.technician).action_start()
        first.with_user(self.technician).action_done()
        second.with_user(self.technician).action_start()
        second.with_user(self.technician).action_done()
        overlap.cancellation_reason = 'Redundant task'
        overlap.action_cancel()
        job.action_progress()
        self.assertEqual(job.state, 'quality_check')

    def test_reserved_issued_consumed_and_returned_stock(self):
        company = self.env.company
        warehouse = self.env['stock.warehouse'].search([('company_id', '=', company.id)], limit=1)
        if not warehouse:
            warehouse = self.env['stock.warehouse'].create({'name': 'Garage warehouse', 'code': 'GAR', 'company_id': company.id})
        workshop = self.env['stock.location'].create({'name': 'Workshop staging', 'usage': 'internal', 'company_id': company.id})
        consumption = self.env['stock.location'].create({'name': 'Workshop consumption', 'usage': 'production', 'company_id': company.id})
        company.write({
            'garage_stock_warehouse_id': warehouse.id, 'garage_workshop_location_id': workshop.id,
            'garage_consumption_location_id': consumption.id,
        })
        quants = self.env['stock.quant']
        quants._update_available_quantity(self.part, warehouse.lot_stock_id, 5)
        job = self._job()
        order = self._authorize(job)
        self.assertFalse(order.picking_ids)
        reservation = self.env['garage.stock.reservation'].with_user(self.manager).create({
            'job_id': job.id, 'product_id': self.part.id, 'quantity': 2,
        })
        reservation.action_reserve()
        self.assertEqual(reservation.state, 'assigned')
        reservation.action_reserve()
        model = self.env['garage.part.movement']
        issue = model.with_user(self.manager).create({
            'job_id': job.id, 'product_id': self.part.id, 'quantity': 2, 'kind': 'issue',
            'reason': 'Repair', 'garage_reservation_id': reservation.id,
        })
        self.assertEqual(issue.garage_stock_move_ids.state, 'done')
        for kind, user in [('consume', self.technician), ('return', self.manager)]:
            model.with_user(user).create({
                'job_id': job.id, 'product_id': self.part.id, 'quantity': 1, 'kind': kind, 'reason': 'Repair',
            })
        self.assertEqual(quants._get_available_quantity(self.part, warehouse.lot_stock_id), 4)
        self.assertEqual(quants._get_available_quantity(self.part, workshop), 0)

    def test_purchase_request_approval_and_retry(self):
        req = self.env['garage.purchase.request'].with_user(self.buyer).with_context(default_state='approved').create({
            'product_id': self.part.id, 'quantity': 2, 'needed_by': fields.Date.today(), 'reason': 'Replenish',
            'vendor_id': self.partner_b.id,
        })
        self.assertEqual(req.state, 'draft')
        req.action_submit()
        with self.assertRaises(AccessError), self.env.cr.savepoint():
            req.action_approve()
        req.with_user(self.approver).action_approve()
        order_id = req.action_create_rfq()['res_id']
        self.assertEqual(req.action_create_rfq()['res_id'], order_id)
        order = self.env['purchase.order'].with_user(self.buyer).browse(order_id)
        with self.assertRaises(AccessError), self.env.cr.savepoint():
            order.button_confirm()
        order.with_user(self.approver).button_confirm()
        self.assertEqual(order.state, 'purchase')
        line = order.order_line
        bill = self.env['account.move'].create({
            'move_type': 'in_invoice', 'partner_id': order.partner_id.id,
            'invoice_date': fields.Date.today(),
            'invoice_line_ids': [Command.create({
                'product_id': line.product_id.id, 'purchase_line_id': line.id,
                'quantity': 2, 'price_unit': 20,
                'account_id': self.company_data['default_account_expense'].id,
            })],
        })
        with self.assertRaisesRegex(ValidationError, 'accepted receipt quantity'), self.env.cr.savepoint():
            bill.action_post()
        self.assertEqual(bill.state, 'draft')

    def test_entitlement_limit_and_claim_evidence(self):
        today = fields.Date.today()
        contract = self.env['garage.service.contract'].with_user(self.manager).create({
            'customer_id': self.partner_a.id, 'vehicle_ids': [Command.link(self.vehicle.id)], 'kind': 'amc',
            'date_start': today - timedelta(days=1), 'date_end': today + timedelta(days=30),
            'visit_limit': 1, 'coverage_limit': 50, 'contract_value': 100, 'terms': 'One visit',
        })
        contract.action_activate()
        job = self._job()
        entitlement = self.env['garage.contract.entitlement'].with_user(self.manager).create({
            'job_id': job.id, 'contract_id': contract.id, 'scope': 'Filter', 'amount': 40,
        })
        entitlement.action_approve()
        self.assertEqual(contract.committed_coverage, 40)
        excess = entitlement.copy({'job_id': self._job().id, 'amount': 20})
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            excess.action_approve()
        order = self._authorize(job)
        claim = self.env['garage.insurance.claim'].with_user(self.manager).create({
            'name': 'Claim 001', 'policy_reference': 'Policy 001', 'job_id': job.id, 'estimate_id': order.id,
            'insurer_id': self.partner_b.id, 'assessment': 'Verified damage', 'insurer_share': 30, 'customer_share': 10,
        })
        claim.action_submit()
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            claim.action_approve()
        claim.approval_evidence = 'Written surveyor confirmation'
        claim.action_approve()
        self.assertEqual(claim.outstanding, 30)

    def test_campaign_rechecks_withdrawn_consent(self):
        partner = self.partner_a
        partner.write({
            'company_id': self.env.company.id, 'is_garage_customer': True,
            'garage_marketing_consent': True, 'email': 'garage-recipient@example.invalid',
        })
        mailing = self.env['mailing.mailing'].sudo().create({
            'subject': 'Workshop campaign',
            'garage_campaign_company_id': self.env.company.id,
            'mailing_model_id': self.env['ir.model']._get_id('res.partner'),
            'mailing_domain': repr([('id', '=', partner.id)]),
        })
        self.assertIn(partner.id, mailing._get_recipients())
        partner.garage_marketing_consent = False
        self.assertNotIn(partner.id, mailing._get_recipients())
