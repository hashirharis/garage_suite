from odoo import api, fields, models, Command, _
from odoo.exceptions import AccessError, ValidationError


class Appointment(models.Model):
    _name = 'garage.appointment'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'Workshop Appointment'
    _check_company_auto = True
    _order = 'start desc'
    name = fields.Char(default='New', readonly=True, copy=False)
    company_id = fields.Many2one('res.company', required=True, default=lambda s: s.env.company)
    customer_id = fields.Many2one('res.partner', required=True, check_company=True)
    vehicle_id = fields.Many2one('garage.vehicle', required=True, check_company=True)
    bay_id = fields.Many2one('garage.service.bay', check_company=True)
    start = fields.Datetime(required=True)
    end = fields.Datetime(required=True)
    complaint = fields.Text(required=True)
    odometer = fields.Float()
    state = fields.Selection([('booked', 'Booked'), ('arrived', 'Arrived'), ('converted', 'Job Created'), ('cancelled', 'Cancelled'), ('no_show', 'No-show')], default='booked', required=True, tracking=True)
    change_reason = fields.Text(tracking=True)
    job_ids = fields.One2many('garage.job.card', 'appointment_id')

    @api.constrains('start', 'end', 'bay_id', 'state', 'customer_id', 'vehicle_id')
    def _check_booking(self):
        for rec in self:
            if rec.end <= rec.start or rec.customer_id != rec.vehicle_id.customer_id:
                raise ValidationError(_('Check the appointment times and vehicle owner.'))
            if rec.bay_id and rec.state in ('booked', 'arrived'):
                self.env.cr.execute('SELECT id FROM garage_service_bay WHERE id = %s FOR UPDATE', [rec.bay_id.id])
                if self.search_count([('id', '!=', rec.id), ('bay_id', '=', rec.bay_id.id), ('state', 'in', ['booked', 'arrived']), ('start', '<', rec.end), ('end', '>', rec.start)]):
                    raise ValidationError(_('This bay is already booked during that interval.'))

    @api.model_create_multi
    def create(self, vals_list):
        self.env['garage.job.card']._require_role('reception')
        for vals in vals_list:
            vals.update(name=self.env['ir.sequence'].next_by_code('garage.appointment'), state='booked')
        return super().create(vals_list)

    def write(self, vals):
        self.env['garage.job.card']._require_role('reception')
        if 'name' in vals or any(r.state in ('converted', 'cancelled', 'no_show') for r in self):
            raise AccessError(_('Terminal appointment evidence is retained.'))
        if {'start', 'end'} & vals.keys() and not (vals.get('change_reason') or '').strip():
            raise ValidationError(_('Record a rescheduling reason.'))
        for rec in self:
            if 'state' in vals:
                allowed = {'booked': ['arrived', 'cancelled', 'no_show'], 'arrived': ['converted', 'cancelled']}
                if vals['state'] not in allowed.get(rec.state, []):
                    raise ValidationError(_('Invalid appointment transition.'))
                if vals['state'] in ('cancelled', 'no_show') and not (vals.get('change_reason') or rec.change_reason):
                    raise ValidationError(_('Record a cancellation or no-show reason.'))
                if vals['state'] == 'converted' and not rec.job_ids:
                    raise ValidationError(_('Create the linked job before marking conversion.'))
        return super().write(vals)

    def action_arrived(self):
        self.write({'state': 'arrived'})

    def action_convert(self):
        self.ensure_one()
        self.env.cr.execute('SELECT id FROM garage_appointment WHERE id = %s FOR UPDATE', [self.id])
        self.invalidate_recordset()
        job = self.job_ids[:1]
        if not job:
            if self.state != 'arrived':
                raise ValidationError(_('Mark the vehicle arrived before creating its job card.'))
            job = self.env['garage.job.card'].create({'appointment_id': self.id, 'vehicle_id': self.vehicle_id.id, 'customer_id': self.customer_id.id, 'company_id': self.company_id.id, 'bay_id': self.bay_id.id, 'expected_delivery': self.end if self.end > fields.Datetime.now() else False, 'odometer': self.odometer, 'complaint_ids': [Command.create({'name': self.complaint})]})
            self.write({'state': 'converted'})
        return {'type': 'ir.actions.act_window', 'res_model': 'garage.job.card', 'res_id': job.id, 'views': [(False, 'form')]}


class Job(models.Model):
    _inherit = 'garage.job.card'
    appointment_id = fields.Many2one('garage.appointment', check_company=True, copy=False, ondelete='restrict')
    @api.constrains('appointment_id', 'vehicle_id', 'customer_id', 'company_id')
    def _check_appointment_source(self):
        for job in self.filtered('appointment_id'):
            appointment = job.appointment_id
            if appointment.vehicle_id != job.vehicle_id or appointment.customer_id != job.customer_id or appointment.company_id != job.company_id:
                raise ValidationError(_('The source appointment and service visit must have the same customer, vehicle and company.'))

    def write(self, vals):
        if 'appointment_id' in vals:
            raise AccessError(_('Source appointments are retained.'))
        return super().write(vals)

    _appointment_unique = models.Constraint('UNIQUE(appointment_id)', 'An appointment can create only one service visit.')
