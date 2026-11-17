from odoo import api, fields, models


class GarageCustomer(models.Model):
    _inherit = 'res.partner'

    garage_vehicle_count = fields.Integer(compute='_compute_garage_counts', groups='garage_core.group_garage_staff')
    garage_visit_count = fields.Integer(compute='_compute_garage_counts', groups='garage_core.group_garage_staff')

    @api.depends('garage_vehicle_ids', 'garage_job_card_ids')
    @api.depends_context('uid', 'company')
    def _compute_garage_counts(self):
        for partner in self:
            partner.garage_vehicle_count = len(partner.garage_vehicle_ids)
            partner.garage_visit_count = len(partner.garage_job_card_ids)


class GarageMenu(models.Model):
    _inherit = 'ir.ui.menu'

    @api.model
    def _visible_menu_ids(self, debug=False):
        visible = super()._visible_menu_ids(debug)
        if self.env.user.has_group('garage_core.group_garage_staff'):
            dashboard = self.env.ref('spreadsheet_dashboard.spreadsheet_dashboard_menu_root', raise_if_not_found=False)
            if dashboard:
                return visible - {dashboard.id}
        return visible
