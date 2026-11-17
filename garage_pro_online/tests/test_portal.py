from odoo.tests import HttpCase, new_test_user, tagged


@tagged('post_install', '-at_install')
class TestGaragePortal(HttpCase):

    def test_visit_history_is_scoped_to_recorded_customer(self):
        company = self.env.ref('website.default_website').company_id
        users = [
            new_test_user(self.env, login=login, password='test-garage-portal', groups='base.group_portal')
            for login in ('garage_portal_owner', 'garage_portal_other')
        ]
        visits = []
        for number, user in enumerate(users, 1):
            vehicle = self.env['garage.vehicle'].sudo().with_company(company).create({
                'company_id': company.id, 'customer_id': user.partner_id.id,
                'registration_number': f'PORTAL-TEST-{number}', 'make': 'Example', 'model': 'Vehicle',
            })
            visits.append(self.env['garage.job.card'].sudo().with_company(company).create({
                'company_id': company.id, 'vehicle_id': vehicle.id,
                'customer_id': user.partner_id.id, 'odometer': 10,
            }))
        self.authenticate('garage_portal_owner', 'test-garage-portal')
        response = self.url_open('/my/garage-visits')
        self.assertEqual(response.status_code, 200)
        self.assertIn(visits[0].name, response.text)
        self.assertIn('PORTAL-TEST-1', response.text)
        self.assertNotIn('PORTAL-TEST-2', response.text)
        self.assertNotIn(visits[1].name, response.text)
