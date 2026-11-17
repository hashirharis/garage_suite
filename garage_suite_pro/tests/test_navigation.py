from odoo.tests import TransactionCase, new_test_user


class TestGarageNavigation(TransactionCase):
    def test_pro_replaces_navigation_under_stable_garage_root(self):
        technician = new_test_user(self.env, login='pro_navigation_tech', groups='garage_core.group_garage_technician')
        menu_model = self.env['ir.ui.menu'].with_user(technician)
        root = self.env.ref('garage_core.menu_garage_root')
        pro_action = self.env.ref('garage_suite_pro.action_dashboard')
        menus = menu_model.load_menus(False)
        self.assertIn(root.id, menus['root']['children'])
        self.assertEqual(menus[root.id]['xmlid'], 'garage_core.menu_garage_root')
        self.assertEqual(menus[root.id]['name'], 'Garage Suite Pro')
        self.assertEqual(menus[root.id]['action_id'], pro_action.id)
        self.assertEqual(menus[root.id]['action_path'], 'garage-pro-overview')
        self.assertIn(self.env.ref('garage_suite_pro.menu_tasks').id, menus)
        self.assertIn(self.env.ref('garage_basic_reports.reports_menu').id, menus)
        self.assertNotIn(self.env.ref('garage_suite_basic.menu_dashboard').id, menus)
        self.assertNotIn(self.env.ref('garage_suite_pro.menu_profit').id, menus)
        self.assertNotIn(self.env.ref('garage_service_master.configuration').id, menus)
        for child_id in menus[root.id]['children']:
            self.assertEqual(menus[child_id]['app_id'], root.id)
        roots = menu_model.load_menus_root()['children']
        self.assertEqual([menu['name'] for menu in roots if menu['id'] == root.id], ['Garage Suite Pro'])
        self.assertEqual(root.action, self.env.ref('garage_suite_basic.action_dashboard'))

    def test_pro_performance_uses_current_company_and_privileges(self):
        executive = new_test_user(self.env, login='pro_navigation_exec', groups='garage_suite_pro.group_garage_executive')
        technician = new_test_user(self.env, login='pro_performance_tech', groups='garage_core.group_garage_technician')
        jobs = self.env['garage.job.card'].with_user(executive)
        payload = jobs.get_dashboard('90')['pro']
        self.assertEqual(payload['received'], jobs.search_count(payload['reception_domain']))
        self.assertEqual(payload['closed'], jobs.search_count(payload['closed_domain']))
        self.assertIn(('company_id', '=', jobs.env.company.id), payload['profitability']['domain'])
        self.assertEqual(len(payload['profitability']['months']), 12)
        self.assertIsNone(jobs.with_user(technician).get_dashboard('90')['pro']['profitability'])
