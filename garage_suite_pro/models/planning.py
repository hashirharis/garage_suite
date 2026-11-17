from datetime import timezone

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, ValidationError
from odoo.tools import SQL, float_compare


class WorkshopTask(models.Model):
    _name = 'garage.workshop.task'
    _description = 'Garage Workshop Task'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'planned_start, sequence, id'
    _check_company_auto = True

    name = fields.Char(required=True, tracking=True)
    sequence = fields.Integer(default=10)
    job_id = fields.Many2one('garage.job.card', required=True, check_company=True, ondelete='restrict', index=True, tracking=True)
    company_id = fields.Many2one(related='job_id.company_id', store=True, index=True)
    operation_line_id = fields.Many2one('garage.job.card.line', check_company=True, ondelete='restrict')
    employee_id = fields.Many2one('hr.employee', required=True, check_company=True, ondelete='restrict', tracking=True)
    technician_id = fields.Many2one(related='employee_id.user_id', store=True, index=True)
    bay_id = fields.Many2one('garage.service.bay', check_company=True, ondelete='restrict', tracking=True)
    predecessor_ids = fields.Many2many('garage.workshop.task', 'garage_task_predecessor_rel', 'task_id', 'predecessor_id', string='Blocked by', check_company=True)
    successor_ids = fields.Many2many('garage.workshop.task', 'garage_task_predecessor_rel', 'predecessor_id', 'task_id', string='Blocks', readonly=True)
    planned_start = fields.Datetime(required=True, tracking=True, index=True)
    planned_end = fields.Datetime(required=True, tracking=True)
    planned_hours = fields.Float(compute='_compute_hours', store=True)
    actual_hours = fields.Float(compute='_compute_hours', store=True)
    time_entry_ids = fields.One2many('garage.job.time.entry', 'garage_task_id')
    state = fields.Selection([
        ('draft', 'Draft'), ('scheduled', 'Scheduled'), ('working', 'In Progress'),
        ('done', 'Done'), ('cancelled', 'Cancelled'),
    ], required=True, default='draft', copy=False, tracking=True, index=True)
    cancellation_reason = fields.Text(copy=False)
    work_notes = fields.Text()
    completed_at = fields.Datetime(readonly=True, copy=False)
    completed_by = fields.Many2one('res.users', readonly=True, copy=False)

    @api.depends('planned_start', 'planned_end', 'time_entry_ids.hours')
    def _compute_hours(self):
        for task in self:
            task.planned_hours = (task.planned_end - task.planned_start).total_seconds() / 3600 if task.planned_end and task.planned_start else 0
            task.actual_hours = sum(task.time_entry_ids.mapped('hours'))

    def _require_planner(self):
        if not self.env.user.has_group('garage_suite_pro.group_garage_planner'):
            raise AccessError(_('Only a Garage Workshop Planner can change the schedule.'))

    def _require_assignee(self):
        if not self.env.user.has_group('garage_suite_pro.group_garage_planner') and any(
            task.technician_id != self.env.user for task in self
        ):
            raise AccessError(_('Only the assigned technician or a planner can progress a task.'))

    def _lock_jobs(self):
        # A row update serializes changes to dependencies and job readiness under PostgreSQL repeatable read.
        self.job_id.flush_recordset(['write_date'])
        for job_id in sorted(self.job_id.ids):
            self.env.cr.execute(SQL('UPDATE garage_job_card SET write_date = write_date WHERE id = %s', job_id))

    @api.model_create_multi
    def create(self, vals_list):
        self._require_planner()
        for vals in vals_list:
            if vals.get('state', 'draft') != 'draft' or {'completed_at', 'completed_by', 'successor_ids'} & vals.keys():
                raise AccessError(_('Create tasks in Draft and use the workflow actions.'))
            vals.update(state='draft', completed_at=False, completed_by=False, successor_ids=[])
        tasks = super().create(vals_list)
        tasks._lock_jobs()
        tasks._validate_plan()
        return tasks

    def write(self, vals):
        if {'state', 'completed_at', 'completed_by', 'successor_ids', 'job_id', 'company_id'} & vals.keys():
            raise AccessError(_('Use the workflow actions and keep the original job reference.'))
        planning_fields = set(vals) - {'work_notes', 'message_follower_ids', 'activity_ids'}
        if planning_fields:
            self._require_planner()
            if planning_fields - {'cancellation_reason'} and any(task.state != 'draft' for task in self):
                raise ValidationError(_('Return a scheduled task to Draft before changing its plan.'))
            self._lock_jobs()
        else:
            self._require_assignee()
        if self.filtered(lambda task: task.state in ('done', 'cancelled')) and set(vals) - {'message_follower_ids', 'activity_ids'}:
            raise ValidationError(_('Retain the original completed or cancelled task.'))
        result = super().write(vals)
        if planning_fields - {'cancellation_reason'}:
            self._validate_plan()
        return result

    def _validate_plan(self):
        if self._has_cycle('predecessor_ids'):
            raise ValidationError(_('Task dependencies cannot form a cycle.'))
        for task in self:
            job = task.job_id
            job.check_access('read')
            if job.state in ('ready', 'delivered', 'closed', 'cancelled'):
                raise ValidationError(_('Create or adjust tasks before final readiness.'))
            if task.planned_end <= task.planned_start:
                raise ValidationError(_('The planned end must follow the start.'))
            if task.operation_line_id and task.operation_line_id.job_id != job:
                raise ValidationError(_('Choose an operation from this job card.'))
            if not task.technician_id or task.technician_id not in job.technician_ids:
                raise ValidationError(_('Assign this employee’s linked user to the job card first.'))
            if task.predecessor_ids.filtered(lambda other: other.job_id != job):
                raise ValidationError(_('Dependencies must belong to the same job card.'))
            skills = task.operation_line_id.operation_id.skill_ids
            if skills - task.technician_id.sudo().garage_skill_ids:
                raise ValidationError(_('The assigned employee lacks one or more required operation skills.'))

    def _check_availability(self):
        for model, ids in (('hr.employee', self.employee_id.ids), ('garage.service.bay', self.bay_id.ids)):
            # Write-lock resources to prevent concurrent overlapping reservations.
            for record_id in sorted(ids):
                self.env.cr.execute(SQL('UPDATE %s SET write_date = write_date WHERE id = %s', SQL.identifier(self.env[model]._table), record_id))
        for task in self:
            if task.predecessor_ids.filtered(lambda other: other.state not in ('scheduled', 'working', 'done') or other.planned_end > task.planned_start):
                raise ValidationError(_('Schedule predecessor tasks before the dependent task starts.'))
            if task.successor_ids.filtered(lambda other: other.state in ('scheduled', 'working', 'done') and other.planned_start < task.planned_end):
                raise ValidationError(_('This schedule would overlap a dependent task.'))
            domain = [
                ('id', '!=', task.id), ('state', 'in', ['scheduled', 'working', 'done']),
                ('planned_start', '<', task.planned_end), ('planned_end', '>', task.planned_start),
            ]
            resource_domain = [('employee_id', '=', task.employee_id.id)]
            if task.bay_id:
                resource_domain = ['|', *resource_domain, ('bay_id', '=', task.bay_id.id)]
            # Detect conflicts even when the planner cannot see the conflicting job.
            if self.sudo().search_count(domain + resource_domain):
                raise ValidationError(_('The employee or bay is already scheduled in that interval.'))
            if task.bay_id and self.env['garage.appointment'].sudo().search_count([
                ('bay_id', '=', task.bay_id.id), ('state', 'in', ['booked', 'arrived']),
                ('start', '<', task.planned_end), ('end', '>', task.planned_start),
            ]):
                raise ValidationError(_('The bay is reserved by an appointment in this interval.'))
            employee = task.employee_id.sudo()
            calendar = employee.resource_calendar_id or task.company_id.resource_calendar_id
            if not calendar:
                raise ValidationError(_('Configure working hours for the employee.'))
            start = task.planned_start.replace(tzinfo=timezone.utc)
            end = task.planned_end.replace(tzinfo=timezone.utc)
            intervals = calendar._work_intervals_batch(start, end, resources=employee.resource_id)
            available = sum((until - since).total_seconds() / 3600 for since, until, _metadata in intervals[employee.resource_id.id])
            if float_compare(available, task.planned_hours, precision_digits=4) < 0:
                raise ValidationError(_('The task must fit within the employee’s working hours and approved availability.'))

    def action_schedule(self):
        self.check_access('write')
        self._require_planner()
        self._lock_jobs()
        for task in self:
            if task.state != 'draft':
                raise ValidationError(_('Only draft tasks can be scheduled.'))
            task._validate_plan()
            task._check_availability()
            super(WorkshopTask, task).write({'state': 'scheduled'})

    def action_unschedule(self):
        self.check_access('write')
        self._require_planner()
        self._lock_jobs()
        if any(task.state != 'scheduled' or task.successor_ids.filtered(lambda other: other.state in ('scheduled', 'working', 'done')) for task in self):
            raise ValidationError(_('Unschedule downstream tasks first. Only scheduled tasks can return to Draft.'))
        super().write({'state': 'draft'})

    def action_start(self):
        self.check_access('write')
        self._require_assignee()
        self._lock_jobs()
        for task in self:
            if task.state != 'scheduled' or task.job_id.state != 'in_progress':
                raise ValidationError(_('Start the authorized job before starting its scheduled task.'))
            if task.predecessor_ids.filtered(lambda other: other.state != 'done'):
                raise ValidationError(_('Complete the prerequisite tasks first.'))
            task._validate_plan()
        super().write({'state': 'working'})

    def action_done(self):
        self.check_access('write')
        self._require_assignee()
        self._lock_jobs()
        for task in self:
            if task.state != 'working' or task.job_id.state != 'in_progress':
                raise ValidationError(_('Only tasks in progress on a running job can be completed.'))
            if task.time_entry_ids.filtered(lambda entry: not entry.end):
                raise ValidationError(_('Stop all timers for the task before completing it.'))
            if task.operation_line_id.planned_hours and not task.time_entry_ids:
                raise ValidationError(_('Log completed time on this task before marking it done.'))
        super().write({'state': 'done', 'completed_at': fields.Datetime.now(), 'completed_by': self.env.user.id})

    def action_cancel(self):
        self.check_access('write')
        self._require_planner()
        self._lock_jobs()
        if any(task.state not in ('draft', 'scheduled') or not (task.cancellation_reason or '').strip()
               or task.successor_ids.filtered(lambda other: other.state != 'cancelled') for task in self):
            raise ValidationError(_('Cancel downstream tasks first and record a reason on each draft or scheduled task.'))
        super().write({'state': 'cancelled'})


class GarageJob(models.Model):
    _inherit = 'garage.job.card'

    garage_task_ids = fields.One2many('garage.workshop.task', 'job_id')
    garage_task_count = fields.Integer(compute='_compute_garage_task_count')

    @api.depends('garage_task_ids')
    def _compute_garage_task_count(self):
        for job in self:
            job.garage_task_count = len(job.garage_task_ids)

    def action_garage_tasks(self):
        self.ensure_one()
        self.check_access('read')
        action = self.env['ir.actions.actions']._for_xml_id('garage_suite_pro.action_tasks')
        action.update(domain=[('job_id', '=', self.id)], context={'default_job_id': self.id})
        return action

    def _check_state_transition(self, target):
        if target in ('quality_check', 'cancelled'):
            self.flush_recordset(['write_date'])
            for job_id in sorted(self.ids):
                self.env.cr.execute(SQL('UPDATE garage_job_card SET write_date = write_date WHERE id = %s', job_id))
            if self.env['garage.workshop.task'].sudo().search_count([
                ('job_id', 'in', self.ids), ('state', 'not in', ['done', 'cancelled'] if target == 'quality_check' else ['cancelled']),
            ]):
                raise ValidationError(_('Resolve the workshop tasks before progressing this job.'))
        return super()._check_state_transition(target)


class TimeEntry(models.Model):
    _inherit = 'garage.job.time.entry'

    garage_task_id = fields.Many2one('garage.workshop.task', check_company=True, ondelete='restrict', index=True)

    def _check_scope(self):
        linked = self.filtered('garage_task_id')
        linked.garage_task_id.check_access('read')
        linked.garage_task_id._lock_jobs()
        super()._check_scope()
        for entry in linked:
            task = entry.garage_task_id
            if (task.state != 'working' or task.job_id != entry.job_id or task.technician_id != entry.technician_id
                    or task.operation_line_id != entry.operation_line_id):
                raise ValidationError(_('Log time against a running task for your job and operation.'))


class GarageAppointment(models.Model):
    _inherit = 'garage.appointment'

    @api.constrains('bay_id', 'start', 'end', 'state')
    def _check_pro_bay_schedule(self):
        for appointment in self.filtered(lambda rec: rec.bay_id and rec.state in ('booked', 'arrived')).sorted('bay_id'):
            self.env.cr.execute(SQL(
                'UPDATE garage_service_bay SET write_date = write_date WHERE id = %s', appointment.bay_id.id,
            ))
            if self.env['garage.workshop.task'].sudo().search_count([
                ('bay_id', '=', appointment.bay_id.id), ('state', 'in', ['scheduled', 'working', 'done']),
                ('planned_start', '<', appointment.end), ('planned_end', '>', appointment.start),
            ]):
                raise ValidationError(_('A workshop task already reserves the bay in this interval.'))
