from odoo import fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    is_garage_customer = fields.Boolean(string='Garage Customer', index=True)
    garage_notes = fields.Text(string='Workshop Notes')
    garage_vehicle_ids = fields.One2many('garage.vehicle', 'customer_id', string='Vehicles')
    garage_job_card_ids = fields.One2many('garage.job.card', 'customer_id', string='Job Cards')
