from odoo import api, fields, models, _
from odoo.exceptions import AccessError, ValidationError


class Partner(models.Model):
    _inherit = 'res.partner'
    garage_service_consent = fields.Boolean(string='Service Reminder Consent', tracking=True)
    garage_marketing_consent = fields.Boolean(string='Marketing Consent', tracking=True)
    garage_estimate_ids = fields.One2many('sale.order', 'partner_id', domain=[('garage_job_id', '!=', False)], groups='garage_core.group_garage_user,garage_core.group_garage_cashier,garage_core.group_garage_owner')
    garage_preferred_channel = fields.Selection([('phone', 'Phone'), ('email', 'Email'), ('sms', 'SMS'), ('whatsapp', 'WhatsApp')], default='phone')


class Reminder(models.Model):
    _name = 'garage.service.reminder'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'Service Reminder and Feedback'
    _check_company_auto = True
    name = fields.Char(required=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda s: s.env.company)
    customer_id = fields.Many2one('res.partner', required=True, check_company=True)
    vehicle_id = fields.Many2one('garage.vehicle', required=True, check_company=True)
    job_id = fields.Many2one('garage.job.card', check_company=True)
    due_date = fields.Date(required=True)
    due_odometer = fields.Float()
    kind = fields.Selection([('service', 'Next Service'), ('insurance', 'Insurance Expiry'), ('puc', 'Pollution Certificate'), ('repair', 'Repair Follow-up')], default='service', required=True)
    state = fields.Selection([('pending', 'Pending'), ('done', 'Followed Up'), ('cancelled', 'Cancelled')], default='pending', tracking=True)
    feedback = fields.Text()
    satisfaction = fields.Selection([(str(n), str(n)) for n in range(1, 6)], string='Satisfaction (1–5)')
    source_key = fields.Char(readonly=True, copy=False)
    _source_unique = models.Constraint('UNIQUE(source_key)', 'This vehicle expiry reminder already exists.')
    assigned_id = fields.Many2one('res.users', default=lambda s: s.env.user)
    channel = fields.Selection(related='customer_id.garage_preferred_channel')
    contact_permitted = fields.Boolean(related='customer_id.garage_service_consent')
    _job_reminder_unique = models.Constraint('UNIQUE(job_id, kind)', 'This follow-up already exists for the visit.')

    def action_followed_up(self):
        for rec in self:
            if rec.customer_id != rec.vehicle_id.customer_id:
                raise ValidationError(_('Ownership changed. Review the current customer before making contact.'))
            if not rec.customer_id.garage_service_consent:
                raise ValidationError(_('Service contact consent is required. Record internal notes instead.'))
        self.write({'state': 'done'})

    @api.model
    def _cron_due_activities(self):
        from datetime import timedelta
        for company in self.env['res.company'].search([]):
            cutoff = fields.Date.today() + timedelta(days=company.garage_reminder_lead_days)
            vehicles = self.env['garage.vehicle'].search([('company_id', '=', company.id)])
            for vehicle in vehicles:
                for kind, date in [('insurance', vehicle.insurance_expiry), ('puc', vehicle.pollution_expiry)]:
                    if not date or date > cutoff:
                        continue
                    source_key = '%s:%s:%s:%s' % (vehicle.id, vehicle.customer_id.id, kind, date)
                    if not self.search_count([('source_key', '=', source_key)]):
                        self.create({'name': _('Vehicle document expiry: %s', vehicle.name), 'company_id': company.id, 'customer_id': vehicle.customer_id.id, 'vehicle_id': vehicle.id, 'due_date': date, 'kind': kind, 'source_key': source_key, 'assigned_id': False})
        for reminder in self.search([('state', '=', 'pending'), ('due_date', '<=', fields.Date.today())]):
            if not reminder.activity_ids and reminder.assigned_id:
                reminder.activity_schedule('mail.mail_activity_data_todo', user_id=reminder.assigned_id.id, summary=_('Review due workshop follow-up'))


class Job(models.Model):
    _inherit = 'garage.job.card'
    def write(self, vals):
        result = super().write(vals)
        if vals.get('state') == 'closed':
            from dateutil.relativedelta import relativedelta
            for job in self:
                vehicle = job.vehicle_id
                if vehicle.customer_id == job.customer_id and vehicle.service_interval_months and not self.env['garage.service.reminder'].search_count([('job_id', '=', job.id), ('kind', '=', 'service')]):
                    self.env['garage.service.reminder'].create({'name': _('Next service: %s', vehicle.name), 'job_id': job.id, 'customer_id': job.customer_id.id, 'vehicle_id': vehicle.id, 'company_id': job.company_id.id, 'due_date': fields.Date.context_today(job) + relativedelta(months=vehicle.service_interval_months), 'due_odometer': job.odometer + vehicle.service_interval_km, 'assigned_id': job.advisor_id.id})
        return result
