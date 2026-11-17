from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import TransactionCase, new_test_user


class TestGarageDashboard(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.advisor = new_test_user(cls.env, login='dashboard_advisor', groups='garage_core.group_garage_user')
        cls.customer = cls.env['res.partner'].create({'name': 'Dashboard Customer', 'is_garage_customer': True})
        cls.vehicle = cls.env['garage.vehicle'].with_user(cls.advisor).create({
            'customer_id': cls.customer.id, 'vin': 'DASHVIN', 'make': 'Test', 'model': 'Test'})
        cls.job = cls.env['garage.job.card'].with_user(cls.advisor).create({
            'customer_id': cls.customer.id, 'vehicle_id': cls.vehicle.id, 'odometer': 50})

    def test_counts_match_drilldowns(self):
        model = self.env['garage.job.card'].with_user(self.advisor)
        payload = model.get_dashboard('30')
        self.assertIn(self.job.id, [row['id'] for row in payload['recent']])
        for card in payload['cards']:
            self.assertEqual(card['count'], self.env[card['model']].with_user(self.advisor).search_count(card['domain']))
        self.assertEqual(sum(stage['count'] for stage in payload['pipeline']), payload['total'])
        with self.assertRaises(ValidationError):
            model.get_dashboard('unsafe')

    def test_dashboard_company_and_role_isolation(self):
        initial_count = self.env['garage.job.card'].with_user(self.advisor).search_count([])
        company = self.env['res.company'].create({'name': 'Dashboard Foreign Company'})
        self.env.user.company_ids |= company
        foreign = self.env['garage.vehicle'].with_company(company).create({
            'customer_id': self.customer.id, 'vin': 'FOREIGNDASHVIN', 'make': 'Test', 'model': 'Test'})
        job = self.env['garage.job.card'].with_company(company).create({
            'customer_id': self.customer.id, 'vehicle_id': foreign.id, 'company_id': company.id, 'odometer': 0})
        payload = self.env['garage.job.card'].with_user(self.advisor).get_dashboard('all')
        self.assertNotIn(job.id, [row['id'] for row in payload['recent']])
        self.assertEqual(next(card for card in payload['cards'] if card['key'] == 'visits')['count'], initial_count)
        outsider = new_test_user(self.env, login='dashboard_outsider', groups='base.group_user')
        with self.assertRaises(AccessError):
            self.env['garage.job.card'].with_user(outsider).get_dashboard()

    def test_role_workspaces_and_report_exports(self):
        import base64
        from io import BytesIO
        from zipfile import ZipFile

        manager = new_test_user(self.env, login='dashboard_export_manager',
                                groups='garage_core.group_garage_manager')
        technician = new_test_user(self.env, login='dashboard_tech',
                                   groups='garage_core.group_garage_technician')
        for user, expected in [
            (self.advisor, {'reception', 'advisor'}),
            (technician, {'technician'}),
            (manager, {'management', 'reception', 'advisor', 'technician', 'quality', 'parts', 'billing'}),
        ]:
            payload = self.env['garage.job.card'].with_user(user).get_dashboard()
            self.assertEqual({workspace['key'] for workspace in payload['workspaces']}, expected)
            self.assertEqual(len(payload['trend']), 7)
            if user == technician:
                self.assertFalse(payload['finance'])

        exporter = self.env['garage.report.export'].with_user(manager)
        for key, _label in exporter._report_choices():
            with self.subTest(report=key):
                export = exporter.create({'report_key': key})
                export.action_excel()
                with ZipFile(BytesIO(base64.b64decode(export.file_data))) as workbook:
                    self.assertIn('xl/worksheets/sheet1.xml', workbook.namelist())
                report = self.env.ref('garage_basic_reports.action_export_pdf').with_user(manager)
                html, _kind = report._render_qweb_html('garage_basic_reports.export_pdf', export.ids)
                self.assertIn(b'<table' if export._report_data(500)[2] else b'No records match', html)

        export = exporter.create({'report_key': 'margin'})
        with self.assertRaises(AccessError):
            export.with_user(technician).action_excel()
