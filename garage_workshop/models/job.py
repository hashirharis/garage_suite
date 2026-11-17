from datetime import timedelta
from odoo import api, fields, models, Command, _
from odoo.exceptions import AccessError, ValidationError


class Job(models.Model):
    _inherit = 'garage.job.card'
    estimate_ids = fields.One2many('sale.order', 'garage_job_id', groups='garage_core.group_garage_user,garage_core.group_garage_cashier,garage_core.group_garage_owner')
    inspection_ids = fields.One2many('garage.inspection', 'job_id')
    time_entry_ids = fields.One2many('garage.job.time.entry', 'job_id')
    part_movement_ids = fields.One2many('garage.part.movement', 'job_id')
    inspection_template_ids = fields.Many2many('garage.inspection.template', string='Required Inspection Templates', check_company=True)
    exception_reason = fields.Text(tracking=True, copy=False)
    delivery_acknowledgment = fields.Text(tracking=True, copy=False)
    delivery_recipient = fields.Char(tracking=True, copy=False)
    delivery_signature = fields.Image(copy=False)
    actual_hours = fields.Float(compute='_compute_actual_hours', store=True)
    closed_at = fields.Datetime(readonly=True, copy=False)
    delivered_at = fields.Datetime(readonly=True, copy=False)
    work_revision = fields.Integer(default=0, readonly=True, copy=False)
    hold_reason_id = fields.Many2one('garage.hold.reason', check_company=True, tracking=True)
    hold_category = fields.Selection(related='hold_reason_id.category', store=True)
    hold_resolution = fields.Text(tracking=True, copy=False)
    work_complete = fields.Boolean(tracking=True)

    @api.depends('time_entry_ids.hours')
    def _compute_actual_hours(self):
        for job in self:
            job.actual_hours = sum(job.time_entry_ids.mapped('hours'))

    def _require_role(self, role):
        if self.env.su:
            return
        groups = {'advisor': 'group_garage_user', 'technician': 'group_garage_technician', 'quality': 'group_garage_quality', 'storekeeper': 'group_garage_storekeeper', 'cashier': 'group_garage_cashier', 'manager': 'group_garage_manager'}
        if role == 'reception':
            if self.env.user.has_group('garage_core.group_garage_receptionist') or self.env.user.has_group('garage_core.group_garage_user'):
                return
            raise AccessError(_('A reception role is required.'))
        if not self.env.user.has_group('garage_core.' + groups[role]):
            raise AccessError(_('Your Garage role does not permit this operation.'))

    def _current_estimate(self):
        self.ensure_one()
        self.check_access('read')
        # Private scope verification exposes no quote prices to workshop roles.
        return self.env['sale.order'].sudo().search([('garage_job_id', '=', self.id)], order='garage_version desc', limit=1)

    def _approved_estimate(self):
        self.ensure_one()
        order = self._current_estimate()
        return order if order.garage_consent == 'approved' else self.env['sale.order']

    def _check_release(self):
        raise ValidationError(_('Install service billing to enforce settlement before delivery.'))

    def _phase_passed(self, phase):
        self.ensure_one()
        templates = self.inspection_template_ids.filtered(lambda t: t.phase == phase)
        signed = self.inspection_ids.filtered(lambda i: i.phase == phase and i.state == 'signed' and (phase not in ('final', 'delivery') or i.work_revision == self.work_revision))
        # Final and delivery sign-offs are always mandatory, even without a template default.
        if phase in ('final', 'delivery') and not signed:
            return False
        return all(signed.filtered(lambda i: i.template_id == template) for template in templates)

    def _check_state_transition(self, target):
        transitions = {'draft': {'diagnosing', 'cancelled'}, 'diagnosing': {'awaiting_approval', 'cancelled'},
                      'awaiting_approval': {'authorized', 'diagnosing', 'cancelled'},
                      'authorized': {'in_progress', 'awaiting_approval', 'cancelled'},
                      'in_progress': {'quality_check', 'on_hold'}, 'quality_check': {'ready', 'in_progress'},
                      'ready': {'delivered', 'in_progress'}, 'delivered': {'closed'},
                      'closed': {'in_progress'}, 'on_hold': {'in_progress'}}
        for job in self:
            if target not in transitions.get(job.state, set()):
                raise ValidationError(_('This lifecycle transition is not permitted.'))
            if target in ('diagnosing', 'awaiting_approval', 'authorized', 'delivered', 'closed'):
                job._require_role('advisor')
            if target == 'diagnosing' and (not job.complaint_ids or not job._phase_passed('reception')):
                raise ValidationError(_('Record complaints and complete the required reception inspection.'))
            if target == 'awaiting_approval' and job._current_estimate().garage_consent != 'issued':
                raise ValidationError(_('Issue the current estimate first.'))
            if target in ('authorized', 'in_progress') and not job._approved_estimate():
                raise ValidationError(_('The current scope must have valid recorded customer approval.'))
            if target in ('in_progress', 'quality_check', 'on_hold'):
                job._require_role('technician')
                if self.env.user not in job.technician_ids and not self.env.user.has_group('garage_core.group_garage_manager'):
                    raise AccessError(_('Only assigned technicians may progress this visit.'))
            if target == 'in_progress' and job.state in ('closed', 'quality_check', 'ready') and not (job.exception_reason or '').strip():
                raise ValidationError(_('Record the manager reason for reopening or rework.'))
            if target == 'in_progress' and job.state == 'on_hold' and not (job.hold_resolution or '').strip():
                raise ValidationError(_('Record how the hold was resolved before resuming.'))
            if target == 'in_progress':
                if not job.technician_ids or not job._phase_passed('technical'):
                    raise ValidationError(_('Assign technicians and complete required technical inspections.'))
                if job.state in ('quality_check', 'ready', 'closed'):
                    job._require_role('manager')
                    if not job.exception_reason:
                        raise ValidationError(_('Record a rework or reopening reason.'))
                if job.state == 'on_hold' and job.prior_state != 'in_progress':
                    raise ValidationError(_('Resume the prior valid operational state.'))
            if target == 'on_hold' and (not job.hold_reason_id or not job.hold_reason or not job.hold_responsible_id):
                raise ValidationError(_('Record the hold reason and responsible person.'))
            if target == 'quality_check' and any(l.planned_hours > 0 and not job.time_entry_ids.filtered(lambda t: t.operation_line_id == l and t.end) for l in job.line_ids):
                raise ValidationError(_('Record completed technician time for every planned labour operation.'))
            if target == 'quality_check' and (not job.work_complete or job.time_entry_ids.filtered(lambda t: not t.end)):
                raise ValidationError(_('Complete the work and stop running labour timers before quality checks.'))
            if target == 'ready':
                job._require_role('quality')
                if any(sum(job.part_movement_ids.filtered(lambda m: m.product_id == p and m.kind == 'issue').mapped('quantity')) != sum(job.part_movement_ids.filtered(lambda m: m.product_id == p and m.kind in ('consume','return')).mapped('quantity')) for p in job.part_movement_ids.product_id):
                    raise ValidationError(_('Reconcile issued parts to consumption and returns before readiness.'))
                if not job._phase_passed('final'):
                    raise ValidationError(_('Signed final quality checks must pass before readiness.'))
            if target == 'delivered':
                if not job._phase_passed('delivery') or not job.delivery_recipient or not job.delivery_acknowledgment:
                    raise ValidationError(_('Complete delivery checks and record the recipient and acknowledgment.'))
                job._check_release()
            if target == 'closed' and not job.delivered_at:
                raise ValidationError(_('Record delivery before closing the visit.'))
            if target == 'cancelled':
                job._require_role('manager')
                if not job.cancellation_reason or job.part_movement_ids or job.time_entry_ids :
                    raise ValidationError(_('Use a cancellation reason. Visits with approved work, time or parts require reconciliation before cancellation.'))

    def _transition_audit_values(self, target):
        values = super()._transition_audit_values(target)
        if target == 'on_hold':
            values['prior_state'] = 'in_progress'
            values['hold_resolution'] = False
        if target == 'delivered':
            values['delivered_at'] = fields.Datetime.now()
        if target == 'closed':
            values['closed_at'] = fields.Datetime.now()
        if target == 'in_progress' and any(j.state in ('closed', 'quality_check', 'ready') for j in self):
            self.ensure_one()
            values['work_revision'] = self.work_revision + 1
            values['work_complete'] = False
        return values

    @api.model_create_multi
    def create(self, vals_list):
        self._require_role('reception')
        for vals in vals_list:
            if any(vals.get(key) for key in ('closed_at', 'delivered_at', 'work_revision', 'work_complete')):
                raise AccessError(_('Workflow evidence is generated by lifecycle actions.'))
            for key in ('delivered_at', 'closed_at'):
                vals[key] = False
            if 'inspection_template_ids' not in vals:
                company_id = vals.get('company_id') or self.env.company.id
                templates = self.env['garage.inspection.template'].search([('default_for_jobs', '=', True), '|', ('company_id', '=', False), ('company_id', '=', company_id)])
                vals['inspection_template_ids'] = [Command.set(templates.ids)]
        return super().create(vals_list)

    def write(self, vals):
        if {'delivered_at', 'closed_at', 'work_revision'} & vals.keys():
            raise AccessError(_('Delivery and closure timestamps are system controlled.'))
        terminal = self.filtered(lambda j: j.state in ('closed', 'cancelled', 'delivered'))
        if terminal and set(vals) - {'state', 'exception_reason', 'message_follower_ids', 'activity_ids'}:
            raise ValidationError(_('Operational details of terminal visits are retained.'))
        if {'technician_ids', 'advisor_id', 'inspection_template_ids', 'package_id', 'line_ids'} & vals.keys():
            self._require_role('advisor')
        reception_fields = {'customer_id','vehicle_id','odometer','odometer_exception_reason','date','expected_delivery','reception_notes','fuel_level','complaint_ids','service_type','service_type_id','bay_id','priority'}
        if self.env.user.has_group('garage_core.group_garage_receptionist') and set(vals).issubset(reception_fields):
            return super().write(vals)
        if set(vals) - {'state', 'message_follower_ids', 'activity_ids'}:
            is_advisor = self.env.user.has_group('garage_core.group_garage_user')
            if not is_advisor:
                self._require_role('technician')
                if set(vals) - {'diagnosis', 'work_complete', 'hold_reason_id', 'hold_reason', 'hold_responsible_id', 'exception_reason', 'hold_resolution'} or any(self.env.user not in j.technician_ids for j in self):
                    raise AccessError(_('Technicians may update only their assigned work observations and hold details.'))
        return super().write(vals)

    def action_create_estimate(self):
        self.ensure_one()
        self._require_role('advisor')
        latest = self._current_estimate()
        if latest and latest.garage_consent in ('draft', 'issued'):
            return {'type': 'ir.actions.act_window', 'res_model': 'sale.order', 'res_id': latest.id, 'views': [(False, 'form')]}
        if self.state == 'in_progress':
            self.write({'hold_reason_id': self.env.ref('garage_service_master.hold_approval').id, 'hold_reason': _('Scope revision requires fresh consent'), 'hold_responsible_id': self.env.user.id})
            self.write({'state': 'on_hold'})
        lines = []
        if self.package_id:
            lines.append(Command.create({'product_id': self.package_id.product_id.id, 'product_uom_qty': 1}))
        for line in self.line_ids.filtered(lambda l: not l.included_in_package):
            if not line.product_id:
                raise ValidationError(_('Choose a service product for every billable labour operation.'))
            lines.append(Command.create({'product_id': line.product_id.id, 'name': line.name, 'product_uom_qty': 1, 'price_unit': line.labour_charge}))
        if latest:
            # Revisions restate complete scope, including previously approved parts,
            # discounts and tax treatment. Never silently discard prior materials.
            order = latest.with_env(self.env).copy({'garage_job_id': self.id, 'validity_date': fields.Date.context_today(self) + timedelta(days=self.company_id.garage_estimate_validity_days)})
        else:
            order = self.env['sale.order'].with_company(self.company_id).create({'garage_job_id': self.id, 'partner_id': self.customer_id.id, 'company_id': self.company_id.id, 'validity_date': fields.Date.context_today(self) + timedelta(days=self.company_id.garage_estimate_validity_days), 'order_line': lines})
        return {'type': 'ir.actions.act_window', 'res_model': 'sale.order', 'res_id': order.id, 'views': [(False, 'form')]}

    def action_progress(self):
        for job in self:
            next_state = {'authorized': 'in_progress', 'in_progress': 'quality_check', 'quality_check': 'ready', 'ready': 'delivered', 'delivered': 'closed', 'on_hold': 'in_progress'}.get(job.state)
            if not next_state:
                raise ValidationError(_('Use the appropriate diagnosis, consent or manager action.'))
            job.write({'state': next_state})

    def action_hold(self):
        self.write({'state': 'on_hold'})

    def action_rework(self):
        self._require_role('manager')
        self.write({'state': 'in_progress'})

    def action_generate_inspections(self):
        self._require_role('advisor')
        for job in self:
            if not job.inspection_template_ids:
                raise ValidationError(_('Select the required inspection templates first.'))
            for template in job.inspection_template_ids:
                if not job.inspection_ids.filtered(lambda i: i.template_id == template and i.work_revision == job.work_revision):
                    self.env['garage.inspection'].create({'job_id': job.id, 'template_id': template.id})


class Complaint(models.Model):
    _inherit = 'garage.job.complaint'

    def write(self, vals):
        if 'job_id' in vals:
            raise AccessError(_('Complaint source visits cannot be changed.'))
        for complaint in self:
            if complaint.job_id.state in ('delivered', 'closed', 'cancelled'):
                raise ValidationError(_('Completed visit complaint evidence is retained.'))
            if not self.env.user.has_group('garage_core.group_garage_user'):
                complaint.job_id._require_role('technician')
                if self.env.user not in complaint.job_id.technician_ids or set(vals) - {'observation'}:
                    raise AccessError(_('Assigned technicians may update only their observations.'))
        return super().write(vals)
