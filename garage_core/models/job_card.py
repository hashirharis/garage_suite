from odoo import api, fields, models, _
from odoo.exceptions import AccessError, ValidationError


JOB_STATES = [('draft', 'Draft'), ('diagnosing', 'Diagnosing'),
              ('awaiting_approval', 'Awaiting Approval'), ('authorized', 'Authorized'),
              ('in_progress', 'In Progress'), ('on_hold', 'On Hold'),
              ('quality_check', 'Quality Check'), ('ready', 'Ready for Delivery'),
              ('delivered', 'Delivered'), ('closed', 'Closed'), ('cancelled', 'Cancelled')]


class GarageJobCard(models.Model):
    _name = 'garage.job.card'
    _description = 'Garage Job Card'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _check_company_auto = True
    _order = 'date desc, id desc'

    name = fields.Char(default='New', required=True, readonly=True, copy=False, index=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda s: s.env.company, index=True)
    currency_id = fields.Many2one(related='company_id.currency_id')
    date = fields.Datetime(default=fields.Datetime.now, required=True)
    customer_id = fields.Many2one('res.partner', required=True, check_company=True, ondelete='restrict', tracking=True)
    vehicle_id = fields.Many2one('garage.vehicle', required=True, check_company=True, ondelete='restrict', tracking=True)
    registration_at_reception = fields.Char(readonly=True, copy=False)
    vin_at_reception = fields.Char(readonly=True, copy=False)
    odometer = fields.Float(string='Odometer (km)', required=True, tracking=True)
    odometer_exception_reason = fields.Char(tracking=True)
    advisor_id = fields.Many2one('res.users', default=lambda s: s.env.user, required=True, check_company=True, tracking=True)
    technician_ids = fields.Many2many('res.users', string='Technicians', check_company=True, tracking=True)
    service_type = fields.Selection([('general', 'General'), ('periodic', 'Periodic'), ('repair', 'Repair')], default='general', required=True)
    source = fields.Selection([('walk_in', 'Walk-in'), ('complaint', 'Complaint'), ('repeat', 'Repeat Repair'), ('warranty', 'Warranty')], default='walk_in', required=True)
    previous_job_id = fields.Many2one('garage.job.card', check_company=True, ondelete='restrict')
    expected_delivery = fields.Datetime(tracking=True)
    priority = fields.Selection([('0', 'Normal'), ('1', 'Urgent')], default='0')
    service_bay = fields.Char()
    fuel_level = fields.Selection([('empty', 'Empty'), ('quarter', '1/4'), ('half', '1/2'), ('three_quarters', '3/4'), ('full', 'Full')])
    reception_notes = fields.Text(string='Condition and Accessories')
    complaint_ids = fields.One2many('garage.job.complaint', 'job_id', copy=True)
    diagnosis = fields.Text(tracking=True)
    line_ids = fields.One2many('garage.job.card.line', 'job_id', string='Planned Operations', copy=True)
    estimated_cost = fields.Monetary(compute='_compute_plan', store=True)
    estimated_hours = fields.Float(compute='_compute_plan', store=True)
    state = fields.Selection(JOB_STATES, default='draft', required=True, tracking=True, copy=False, index=True)
    cancellation_reason = fields.Text(copy=False, tracking=True)
    cancelled_by = fields.Many2one('res.users', readonly=True, copy=False)
    cancelled_at = fields.Datetime(readonly=True, copy=False)
    hold_reason = fields.Text(tracking=True)
    hold_responsible_id = fields.Many2one('res.users', check_company=True)
    prior_state = fields.Selection(JOB_STATES, readonly=True, copy=False)

    _name_unique = models.Constraint('UNIQUE(company_id, name)', 'Job card reference must be unique.')

    @api.depends('line_ids.planned_hours', 'line_ids.labour_charge')
    def _compute_plan(self):
        for job in self:
            job.estimated_hours = sum(job.line_ids.mapped('planned_hours'))
            job.estimated_cost = sum(job.line_ids.mapped('labour_charge'))

    @api.onchange('vehicle_id')
    def _onchange_vehicle(self):
        if self.vehicle_id:
            self.customer_id = self.vehicle_id.customer_id
            self.odometer = self.vehicle_id.odometer

    @api.constrains('odometer', 'vehicle_id', 'customer_id', 'expected_delivery', 'date', 'previous_job_id')
    def _check_reception(self):
        for job in self:
            if job.odometer < 0:
                raise ValidationError(_('Odometer cannot be negative.'))
            if job.expected_delivery and job.expected_delivery < job.date:
                raise ValidationError(_('Expected delivery must be after reception.'))
            if job.previous_job_id and (job.previous_job_id == job or job.previous_job_id.vehicle_id != job.vehicle_id):
                raise ValidationError(_('A follow-up must reference another visit for the same vehicle.'))

    def _validate_new_reception(self):
        for job in self:
            if job.customer_id != job.vehicle_id.customer_id:
                raise ValidationError(_('Reception customer must be the current vehicle owner.'))
            others = self.search([('vehicle_id', '=', job.vehicle_id.id), ('id', '!=', job.id)])
            if job.odometer < max(others.mapped('odometer'), default=0):
                if not self.env.user.has_group('garage_core.group_garage_manager') or not (job.odometer_exception_reason or '').strip():
                    raise ValidationError(_('A lower odometer requires a manager and an exception reason.'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('state', 'draft') != 'draft':
                raise ValidationError(_('New job cards must start in Draft.'))
            vehicle = self.env['garage.vehicle'].browse(vals.get('vehicle_id'))
            vehicle.check_access('read')
            vals.update(name=self.env['ir.sequence'].next_by_code('garage.job.card') or 'New',
                        registration_at_reception=vehicle.registration_number,
                        vin_at_reception=vehicle.vin,
                        cancelled_by=False, cancelled_at=False, prior_state=False)
        jobs = super().create(vals_list)
        jobs._validate_new_reception()
        return jobs

    def _check_state_transition(self, target):
        # Extensions override this hook only when their server-side gates exist.
        allowed = {'draft': {'diagnosing', 'cancelled'}, 'diagnosing': {'cancelled'}}
        for job in self:
            if target not in allowed.get(job.state, set()):
                raise ValidationError(_('This transition requires a future approval, inspection or billing module.'))
            if target == 'diagnosing' and not job.complaint_ids:
                raise ValidationError(_('Record at least one customer complaint before diagnosis.'))
            if target == 'cancelled':
                if not self.env.user.has_group('garage_core.group_garage_manager'):
                    raise AccessError(_('Only a garage manager may cancel a visit.'))
                if not (job.cancellation_reason or '').strip():
                    raise ValidationError(_('Record a cancellation reason first.'))

    def _transition_audit_values(self, target):
        return {}

    def write(self, vals):
        if {'name', 'registration_at_reception', 'vin_at_reception', 'cancelled_by', 'cancelled_at', 'prior_state'} & vals.keys():
            raise ValidationError(_('System references and audit fields cannot be edited.'))
        if 'company_id' in vals and any(j.company_id.id != vals['company_id'] for j in self):
            raise ValidationError(_('Job cards cannot be moved between companies.'))
        if {'vehicle_id', 'customer_id', 'odometer', 'odometer_exception_reason', 'date'} & vals.keys():
            if any(j.state != 'draft' for j in self):
                raise ValidationError(_('Reception identity and mileage are locked after Draft.'))
        if 'state' in vals:
            changed = self.filtered(lambda j: j.state != vals['state'])
            changed._check_state_transition(vals['state'])
            if changed:
                vals = dict(vals, **changed._transition_audit_values(vals['state']))
            if changed and vals['state'] == 'cancelled':
                vals = dict(vals, cancelled_by=self.env.user.id, cancelled_at=fields.Datetime.now())
        result = super().write(vals)
        if {'vehicle_id', 'customer_id', 'odometer', 'odometer_exception_reason'} & vals.keys():
            self._validate_new_reception()
        return result

    def action_start_diagnosis(self):
        self.write({'state': 'diagnosing'})

    def action_cancel(self):
        self.write({'state': 'cancelled'})


class GarageJobComplaint(models.Model):
    _name = 'garage.job.complaint'
    _description = 'Job Customer Complaint'
    _check_company_auto = True
    _order = 'sequence, id'

    sequence = fields.Integer(default=10)
    job_id = fields.Many2one('garage.job.card', required=True, ondelete='cascade', check_company=True)
    company_id = fields.Many2one(related='job_id.company_id', store=True)
    name = fields.Text(string='Complaint', required=True)
    observation = fields.Text(string='Technician Observation')


class GarageJobCardLine(models.Model):
    _name = 'garage.job.card.line'
    _description = 'Job Planned Labour Operation'
    _check_company_auto = True
    _order = 'sequence, id'

    sequence = fields.Integer(default=10)
    job_id = fields.Many2one('garage.job.card', required=True, ondelete='cascade', check_company=True)
    company_id = fields.Many2one(related='job_id.company_id', store=True)
    currency_id = fields.Many2one(related='job_id.currency_id')
    name = fields.Char(string='Operation', required=True)
    technician_ids = fields.Many2many('res.users', check_company=True)
    planned_hours = fields.Float()
    labour_charge = fields.Monetary()
    notes = fields.Text()

    @api.constrains('planned_hours', 'labour_charge')
    def _check_amounts(self):
        for line in self:
            if line.planned_hours < 0 or line.labour_charge < 0:
                raise ValidationError(_('Planned hours and labour charges cannot be negative.'))
