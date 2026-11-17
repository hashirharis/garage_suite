from odoo import api, fields, models, _
from odoo.exceptions import AccessError, ValidationError


class TimeEntry(models.Model):
    _name = 'garage.job.time.entry'
    _description = 'Technician Labour Time'
    _check_company_auto = True
    _order = 'start desc'
    job_id = fields.Many2one('garage.job.card', required=True, ondelete='restrict', check_company=True)
    company_id = fields.Many2one(related='job_id.company_id', store=True)
    operation_line_id = fields.Many2one('garage.job.card.line', required=True, check_company=True, ondelete='restrict')
    technician_id = fields.Many2one('res.users', required=True, default=lambda s: s.env.user, check_company=True)
    start = fields.Datetime(required=True, default=fields.Datetime.now)
    end = fields.Datetime()
    hours = fields.Float(compute='_compute_hours', store=True)
    notes = fields.Text()
    hourly_cost = fields.Float(compute='_compute_hourly_cost', store=True, compute_sudo=True, readonly=True, groups='garage_core.group_garage_manager,garage_core.group_garage_owner')
    labour_cost = fields.Monetary(compute='_compute_cost', store=True, groups='garage_core.group_garage_manager,garage_core.group_garage_owner')
    currency_id = fields.Many2one(related='company_id.currency_id')

    @api.depends('job_id.name', 'operation_line_id.name')
    @api.depends_context('lang')
    def _compute_display_name(self):
        for entry in self:
            entry.display_name = ' · '.join(filter(None, (entry.job_id.name, entry.operation_line_id.name))) or _('Technician Time')

    @api.depends('technician_id')
    def _compute_hourly_cost(self):
        for rec in self:
            rec.hourly_cost = rec.technician_id.sudo().garage_hourly_cost

    @api.depends('hours', 'hourly_cost')
    def _compute_cost(self):
        for rec in self:
            rec.labour_cost = rec.hours * rec.hourly_cost

    @api.depends('start', 'end')
    def _compute_hours(self):
        for rec in self:
            rec.hours = (rec.end - rec.start).total_seconds() / 3600 if rec.end and rec.start else 0

    def _check_scope(self):
        for rec in self:
            rec.job_id._require_role('technician')
            if rec.technician_id != self.env.user and not self.env.user.has_group('garage_core.group_garage_manager'):
                raise AccessError(_('Record labour for yourself or use a manager account.'))
            if rec.job_id.state != 'in_progress' or rec.technician_id not in rec.job_id.technician_ids or rec.operation_line_id.job_id != rec.job_id:
                raise ValidationError(_('Labour requires an assigned technician, an authorized running visit and its operation.'))
            order = rec.job_id._approved_estimate()
            product = rec.operation_line_id.product_id
            package_product = rec.job_id.package_id.product_id if rec.operation_line_id.included_in_package else False
            if not order or (product not in order.order_line.product_id and package_product not in order.order_line.product_id):
                raise ValidationError(_('This operation is outside the currently approved scope.'))
            if rec.start < order.garage_recorded_at or rec.start < rec.job_id.date:
                raise ValidationError(_('Labour must follow reception and the current customer approval.'))
            if rec.start > fields.Datetime.now() or (rec.end and rec.end > fields.Datetime.now()):
                raise ValidationError(_('Labour timestamps cannot be in the future.'))
            if rec.end and rec.end <= rec.start:
                raise ValidationError(_('Labour end must follow its start.'))
            self.env.cr.execute('SELECT pg_advisory_xact_lock(%s, %s)', [1907, rec.technician_id.id])
            domain = [('id', '!=', rec.id), ('technician_id', '=', rec.technician_id.id), '|', ('end', '=', False), ('end', '>', rec.start)]
            if rec.end:
                domain.append(('start', '<', rec.end))
            if self.sudo().search_count(domain):
                raise ValidationError(_('This technician has an overlapping labour entry.'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            for key in ('hours', 'hourly_cost', 'labour_cost'):
                vals.pop(key, None)
        records = super().create(vals_list)
        records._check_scope()
        return records

    def write(self, vals):
        if set(vals) - {'end', 'notes'} or any(rec.end for rec in self):
            raise AccessError(_('Completed labour evidence is immutable.'))
        result = super().write(vals)
        self._check_scope()
        return result

    def action_stop(self):
        self.write({'end': fields.Datetime.now()})

    def unlink(self):
        raise AccessError(_('Labour entries are retained.'))


class PartMovement(models.Model):
    _name = 'garage.part.movement'
    _description = 'Workshop Part Issue Consumption or Return'
    _check_company_auto = True
    _order = 'id desc'
    job_id = fields.Many2one('garage.job.card', required=True, ondelete='restrict', check_company=True)
    company_id = fields.Many2one(related='job_id.company_id', store=True)
    product_id = fields.Many2one('product.product', required=True, check_company=True, ondelete='restrict', domain="[('type', '=', 'consu')]")
    uom_id = fields.Many2one(related='product_id.uom_id')
    kind = fields.Selection([('issue', 'Issue'), ('consume', 'Consume'), ('return', 'Return')], required=True)
    quantity = fields.Float(required=True)
    reason = fields.Text(required=True)
    currency_id = fields.Many2one(related='company_id.currency_id')
    unit_cost = fields.Monetary(compute='_compute_unit_cost', store=True, compute_sudo=True, readonly=True, groups='garage_core.group_garage_manager,garage_core.group_garage_owner')
    consumed_cost = fields.Monetary(compute='_compute_cost', store=True, groups='garage_core.group_garage_manager,garage_core.group_garage_owner')

    @api.depends('product_id', 'company_id')
    def _compute_unit_cost(self):
        for rec in self:
            rec.unit_cost = rec.product_id.with_company(rec.company_id).sudo().standard_price

    @api.depends('unit_cost', 'quantity', 'kind')
    def _compute_cost(self):
        for rec in self:
            rec.consumed_cost = rec.quantity * rec.unit_cost if rec.kind == 'consume' else 0
    actor_id = fields.Many2one('res.users', readonly=True, required=True)
    recorded_at = fields.Datetime(readonly=True, required=True)

    @api.depends('job_id.name', 'kind', 'product_id.name')
    @api.depends_context('lang')
    def _compute_display_name(self):
        kinds = dict(self._fields['kind']._description_selection(self.env))
        for movement in self:
            activity = ' '.join(filter(None, (kinds.get(movement.kind), movement.product_id.name)))
            movement.display_name = ' · '.join(filter(None, (activity, movement.job_id.name))) or _('Part Movement')

    @api.model_create_multi
    def create(self, vals_list):
        records = self.browse()
        for vals in vals_list:
            job = self.env['garage.job.card'].browse(vals['job_id'])
            role = 'technician' if vals.get('kind') == 'consume' else 'storekeeper'
            job._require_role(role)
            returning = vals.get('kind') == 'return'
            if (not returning and (job.state != 'in_progress' or not job._approved_estimate())) or (returning and job.state not in ('in_progress','on_hold','quality_check','ready')):
                raise ValidationError(_('Parts movements require a running visit with current approved scope.'))
            if role == 'technician' and self.env.user not in job.technician_ids and not self.env.user.has_group('garage_core.group_garage_manager'):
                raise AccessError(_('Only assigned technicians may record consumption.'))
            self.env.cr.execute('SELECT id FROM garage_job_card WHERE id = %s FOR UPDATE', [job.id])
            vals.pop('unit_cost', None)
            vals.pop('consumed_cost', None)
            vals.update(actor_id=self.env.user.id, recorded_at=fields.Datetime.now())
            rec = super().create([vals])
            records |= rec
            if rec.quantity <= 0 or rec.product_id.type != 'consu' or not (rec.reason or '').strip():
                raise ValidationError(_('Use a parts product, positive quantity and reason.'))
            moves = self.search([('job_id', '=', job.id), ('product_id', '=', rec.product_id.id)])
            amounts = {kind: sum(moves.filtered(lambda m: m.kind == kind).mapped('quantity')) for kind in ('issue', 'consume', 'return')}
            approved = sum(line.product_uom_id._compute_quantity(line.product_uom_qty, rec.product_id.uom_id) for line in job._approved_estimate().order_line.filtered(lambda l: l.product_id == rec.product_id))
            if (not returning and amounts['issue'] - amounts['return'] > approved + 0.00001) or amounts['consume'] + amounts['return'] > amounts['issue'] + 0.00001:
                raise ValidationError(_('Issued quantities cannot exceed approval; consumed and returned quantities cannot exceed issues.'))
        return records

    def write(self, vals):
        raise AccessError(_('Parts movements are append-only evidence.'))

    def unlink(self):
        raise AccessError(_('Parts movements are retained.'))
