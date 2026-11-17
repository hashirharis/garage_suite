from psycopg2 import IntegrityError

from odoo import Command
from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import TransactionCase, new_test_user, tagged


@tagged('post_install', '-at_install')
class TestGarageFoundation(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manager = new_test_user(cls.env, login='garage_manager_test', groups='garage_core.group_garage_manager')
        cls.advisor = new_test_user(cls.env, login='garage_advisor_test', groups='garage_core.group_garage_user')
        cls.customer = cls.env['res.partner'].create({'name': 'Garage Customer', 'is_garage_customer': True})
        cls.vehicle = cls.env['garage.vehicle'].with_user(cls.manager).create({
            'customer_id': cls.customer.id, 'registration_number': 'KA 01 AB 1234',
            'vin': 'TESTVIN123', 'make': 'Test Make', 'model': 'Test Model'})

    def job(self, **values):
        return self.env['garage.job.card'].with_user(self.advisor).create(dict({
            'customer_id': self.customer.id, 'vehicle_id': self.vehicle.id,
            'odometer': 100, 'complaint_ids': [Command.create({'name': 'Engine noise'})]}, **values))

    def test_identity_and_history(self):
        with self.assertRaises(AccessError):
            self.vehicle.with_user(self.advisor).write({'registration_number': 'NEW123', 'change_reason': 'New plate'})
        with self.assertRaises(ValidationError):
            self.vehicle.write({'vin': 'NEWVIN'})
        job = self.job()
        new_owner = self.env['res.partner'].create({'name': 'Next Owner'})
        self.vehicle.write({'customer_id': new_owner.id, 'registration_number': 'NEW123', 'change_reason': 'Transfer'})
        self.assertEqual(job.customer_id, self.customer)
        self.assertEqual(job.registration_at_reception, 'KA 01 AB 1234')
        self.assertEqual(len(self.vehicle.history_ids), 2)
        with self.assertRaises(AccessError):
            self.vehicle.history_ids[:1].write({'reason': 'tampered'})

    def test_normalized_duplicates(self):
        for values in ({'vin': 'test-vin 123', 'registration_number': 'OTHER'},
                       {'vin': 'OTHER', 'registration_number': 'ka01-ab1234'}):
            with self.assertRaises(IntegrityError), self.cr.savepoint():
                self.vehicle.copy(values)

    def test_job_guards(self):
        first = self.job()
        second = self.job()
        self.assertNotEqual(first.name, second.name)
        with self.assertRaises(ValidationError):
            self.job(odometer=90)
        with self.assertRaises(ValidationError):
            first.write({'state': 'delivered'})
        if 'inspection_ids' in first._fields:
            first.action_generate_inspections()
            reception = first.inspection_ids.filtered(lambda i: i.phase == 'reception')
            reception.line_ids.write({'result': 'pass'})
            reception.action_sign()
        first.action_start_diagnosis()
        with self.assertRaises(ValidationError):
            first.write({'customer_id': self.customer.id})
        first.write({'cancellation_reason': 'Customer declined inspection'})
        with self.assertRaises(AccessError):
            first.action_cancel()
        first.with_user(self.manager).action_cancel()
        self.assertEqual(first.cancelled_by, self.manager)
        with self.assertRaises(ValidationError):
            first.write({'state': 'draft'})

    def test_company_and_role_isolation(self):
        other = self.env['res.company'].create({'name': 'Other Garage'})
        foreign_vehicle = self.env['garage.vehicle'].with_company(other).create({
            'company_id': other.id, 'customer_id': self.customer.id,
            'vin': 'FOREIGNVIN', 'make': 'Other', 'model': 'Other'})
        with self.assertRaises(AccessError):
            foreign_vehicle.with_user(self.advisor).read(['vin'])
        outsider = new_test_user(self.env, login='garage_outsider', groups='base.group_user')
        with self.assertRaises(AccessError):
            self.vehicle.with_user(outsider).read(['vin'])
        with self.assertRaises(AccessError):
            self.vehicle.with_user(self.advisor).unlink()

    def test_identity_required_and_keys_protected(self):
        with self.assertRaises(ValidationError):
            self.env['garage.vehicle'].with_user(self.advisor).create({
                'customer_id': self.customer.id, 'make': 'Test', 'model': 'Test'})
        with self.assertRaises(ValidationError):
            self.vehicle.write({'vin_key': 'BYPASS'})
        job = self.job()
        with self.assertRaises(ValidationError):
            job.write({'registration_at_reception': 'BYPASS'})
