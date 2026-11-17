from odoo import api, models, _


class GarageMenu(models.Model):
    _inherit = 'ir.ui.menu'

    @api.model
    def _load_menus_blacklist(self):
        # Pro owns the replacement sections. Reports and Configuration continue
        # under the shared root with their existing access rules and links.
        replaced = (
            'garage_suite_basic.menu_dashboard',
            'garage_suite_basic.customers_vehicles',
            'garage_suite_basic.front_desk',
            'garage_core.menu_workshop',
            'garage_suite_basic.commercial',
        )
        hidden_ids = [menu.id for xmlid in replaced if (menu := self.env.ref(xmlid, raise_if_not_found=False))]
        return [*super()._load_menus_blacklist(), *hidden_ids]

    @api.model
    def load_menus(self, debug):
        menus = super().load_menus(debug)
        garage_id = self.env.ref('garage_core.menu_garage_root').id
        action = self.env.ref('garage_suite_pro.action_dashboard', raise_if_not_found=False)
        if not action or garage_id not in menus['root']['children']:
            return menus
        # Odoo caches its menu payload. Copy the entries we decorate.
        return {
            **menus,
            garage_id: {
                **menus[garage_id],
                'name': _('Garage Suite Pro'),
                'action_model': action._name,
                'action_id': action.id,
                'action_path': action.path,
            },
        }

    @api.model
    def load_menus_root(self):
        root = super().load_menus_root()
        garage_id = self.env.ref('garage_core.menu_garage_root').id
        action = self.env.ref('garage_suite_pro.action_dashboard', raise_if_not_found=False)
        if not action:
            return root
        return {
            **root,
            'children': [
                {**menu, 'name': _('Garage Suite Pro'), 'action': f'{action._name},{action.id}'}
                if menu['id'] == garage_id else menu
                for menu in root['children']
            ],
        }
