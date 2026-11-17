from odoo import api, fields, models, Command, _
from odoo.exceptions import AccessError, ValidationError


class Lead(models.Model):
    _inherit = 'crm.lead'
    garage_service_enquiry = fields.Boolean(string='Garage Service Enquiry', index=True)
    garage_vehicle_id = fields.Many2one('garage.vehicle', check_company=True)
    garage_job_ids = fields.One2many('garage.job.card', 'lead_id')
    garage_service_type_id = fields.Many2one('garage.service.type', check_company=True)

    def action_garage_job(self):
        self.ensure_one()
        self.check_access('write')
        self.env['garage.job.card']._require_role('advisor')
        if not self.partner_id or not self.garage_vehicle_id or self.partner_id != self.garage_vehicle_id.customer_id:
            raise ValidationError(_('Link the current vehicle owner and vehicle before creating a service visit.'))
        self.env.cr.execute('SELECT id FROM crm_lead WHERE id = %s FOR UPDATE', [self.id])
        self.invalidate_recordset(['garage_job_ids'])
        job = self.garage_job_ids[:1]
        if not job:
            job = self.env['garage.job.card'].create({'lead_id': self.id, 'customer_id': self.partner_id.id, 'vehicle_id': self.garage_vehicle_id.id, 'company_id': (self.company_id or self.env.company).id, 'odometer': self.garage_vehicle_id.odometer, 'service_type_id': self.garage_service_type_id.id, 'complaint_ids': [Command.create({'name': self.name})]})
        return {'type': 'ir.actions.act_window', 'res_model': 'garage.job.card', 'res_id': job.id, 'views': [(False, 'form')]}


class Job(models.Model):
    _inherit = 'garage.job.card'
    lead_id = fields.Many2one('crm.lead', check_company=True, copy=False, ondelete='restrict')
    _lead_unique = models.Constraint('UNIQUE(lead_id)', 'This CRM enquiry already has a service visit.')


    @api.constrains('lead_id', 'vehicle_id', 'customer_id')
    def _check_lead_source(self):
        for job in self.filtered('lead_id'):
            if job.lead_id.partner_id != job.customer_id or job.lead_id.garage_vehicle_id != job.vehicle_id:
                raise ValidationError(_('The enquiry and visit must reference the same customer and vehicle.'))

    def write(self, vals):
        if 'lead_id' in vals:
            raise AccessError(_('Source enquiries are retained.'))
        return super().write(vals)
