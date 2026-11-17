from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class Company(models.Model):
    _inherit = 'res.company'
    garage_estimate_validity_days = fields.Integer(default=7)
    garage_advisor_discount_limit = fields.Float(default=0, string='Advisor Discount Limit (%)')
    garage_reminder_lead_days = fields.Integer(default=30)

    @api.constrains('garage_estimate_validity_days', 'garage_advisor_discount_limit', 'garage_reminder_lead_days')
    def _check_workshop_settings(self):
        for rec in self:
            if rec.garage_estimate_validity_days < 1 or not 0 <= rec.garage_advisor_discount_limit <= 100 or rec.garage_reminder_lead_days < 0:
                raise ValidationError(_('Choose a positive estimate validity, a discount limit from 0 to 100, and a nonnegative reminder lead time.'))


class Settings(models.TransientModel):
    _inherit = 'res.config.settings'
    garage_estimate_validity_days = fields.Integer(related='company_id.garage_estimate_validity_days', readonly=False)
    garage_advisor_discount_limit = fields.Float(related='company_id.garage_advisor_discount_limit', readonly=False)
    garage_reminder_lead_days = fields.Integer(related='company_id.garage_reminder_lead_days', readonly=False)
