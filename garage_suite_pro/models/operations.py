from datetime import datetime, time, timedelta, timezone

from odoo import Command, api, fields, models, _
from odoo.fields import Domain
from odoo.exceptions import AccessError, ValidationError
from odoo.tools import SQL


class PurchaseRequest(models.Model):
    _name = 'garage.purchase.request'
    _description = 'Garage Parts Purchase Request'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _check_company_auto = True
    _order = 'id desc'

    name = fields.Char(default='New', readonly=True, copy=False, index=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company, index=True)
    job_id = fields.Many2one('garage.job.card', check_company=True, ondelete='restrict')
    product_id = fields.Many2one('product.product', required=True, check_company=True, ondelete='restrict', domain="[('garage_part', '=', True), ('purchase_ok', '=', True)]")
    quantity = fields.Float(required=True)
    uom_id = fields.Many2one(related='product_id.uom_id')
    needed_by = fields.Date(required=True)
    reason = fields.Text(required=True)
    requester_id = fields.Many2one('res.users', required=True, readonly=True, default=lambda self: self.env.user)
    vendor_id = fields.Many2one('res.partner', check_company=True, ondelete='restrict')
    order_ids = fields.One2many('purchase.order', 'garage_request_id', readonly=True)
    state = fields.Selection([('draft', 'Draft'), ('submitted', 'Submitted'), ('approved', 'Approved'), ('cancelled', 'Cancelled')], default='draft', required=True, tracking=True, copy=False)
    approved_by = fields.Many2one('res.users', readonly=True, copy=False)
    approved_at = fields.Datetime(readonly=True, copy=False)
    cancellation_reason = fields.Text(copy=False)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('state', 'draft') != 'draft' or {'approved_by', 'approved_at'} & vals.keys():
                raise AccessError(_('Use the purchase request workflow to record approval.'))
            vals.update(name=self.env['ir.sequence'].next_by_code('garage.purchase.request'), requester_id=self.env.uid,
                        state='draft', approved_by=False, approved_at=False, order_ids=[])
        records = super().create(vals_list)
        records.job_id.check_access('read')
        return records

    @api.constrains('quantity', 'product_id', 'reason')
    def _check_request(self):
        for req in self:
            if req.quantity <= 0 or not req.product_id.garage_part or not req.product_id.purchase_ok or not req.reason.strip():
                raise ValidationError(_('Enter a purchaseable automotive part, positive quantity and business reason.'))

    def _lock_requests(self):
        self.flush_recordset(['write_date'])
        for request_id in sorted(self.ids):
            self.env.cr.execute(SQL('UPDATE garage_purchase_request SET write_date = write_date WHERE id = %s', request_id))

    def write(self, vals):
        if {'state', 'name', 'requester_id', 'approved_by', 'approved_at', 'order_ids'} & vals.keys():
            raise AccessError(_('Use the purchase request workflow buttons.'))
        self._lock_requests()
        if set(vals) - {'vendor_id', 'cancellation_reason', 'activity_ids', 'message_follower_ids'} and self.filtered(lambda req: req.state != 'draft'):
            raise ValidationError(_('Submitted purchase requirements are retained.'))
        result = super().write(vals)
        self.job_id.check_access('read')
        return result

    def action_submit(self):
        self.check_access('write')
        self._lock_requests()
        if any(req.state != 'draft' for req in self):
            raise ValidationError(_('Only draft requests can be submitted.'))
        super().write({'state': 'submitted'})

    def _require_approver(self):
        if not self.env.user.has_group('garage_suite_pro.group_garage_purchase_approver'):
            raise AccessError(_('Garage purchase approval rights are required.'))

    def action_approve(self):
        self.check_access('write')
        self._require_approver()
        self._lock_requests()
        if any(req.state != 'submitted' or req.requester_id == self.env.user for req in self):
            raise ValidationError(_('A different approver must approve the submitted request.'))
        super().write({'state': 'approved', 'approved_by': self.env.uid, 'approved_at': fields.Datetime.now()})

    def action_cancel(self):
        self.check_access('write')
        self._require_approver()
        self._lock_requests()
        if any(req.state == 'cancelled' or not (req.cancellation_reason or '').strip()
               or req.order_ids.filtered(lambda order: order.state != 'cancel') for req in self):
            raise ValidationError(_('Record the reason and cancel the linked RFQs before cancelling the request.'))
        super().write({'state': 'cancelled'})

    def action_create_rfq(self):
        self.ensure_one()
        self.check_access('write')
        self._lock_requests()
        if self.state != 'approved' or not self.vendor_id:
            raise ValidationError(_('Approve the request and choose a vendor first.'))
        order = self.order_ids.filtered(lambda po: po.state != 'cancel' and po.partner_id == self.vendor_id)[:1]
        if not order:
            order = self.env['purchase.order'].with_company(self.company_id).create({
                'partner_id': self.vendor_id.id, 'company_id': self.company_id.id,
                'origin': self.name, 'garage_request_id': self.id, 'state': 'draft',
                'order_line': [Command.create({
                    'product_id': self.product_id.id, 'product_qty': self.quantity,
                    'product_uom_id': self.uom_id.id, 'date_planned': fields.Datetime.to_datetime(self.needed_by),
                })],
            })
        return {'type': 'ir.actions.act_window', 'res_model': 'purchase.order', 'res_id': order.id, 'views': [(False, 'form')]}


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    garage_request_id = fields.Many2one('garage.purchase.request', check_company=True, readonly=True, index=True, copy=False, ondelete='restrict')

    @api.model_create_multi
    def create(self, vals_list):
        orders = super().create(vals_list)
        if orders.filtered(lambda order: order.garage_request_id and order.state != 'draft'):
            raise ValidationError(_('Create request-linked orders as draft RFQs.'))
        return orders

    def write(self, vals):
        if 'garage_request_id' in vals:
            raise AccessError(_('Keep the originating request on its RFQ.'))
        if vals.get('state') in ('purchase', 'done'):
            self._check_garage_award()
        if {'partner_id', 'company_id'} & vals.keys() and self.filtered(
            lambda order: order.garage_request_id and order.state == 'purchase'
        ):
            raise ValidationError(_('The awarded request keeps its original vendor and company.'))
        return super().write(vals)

    def _check_garage_award(self):
        requests = self.garage_request_id
        requests.check_access('read')
        requests._lock_requests()
        for order in self.filtered('garage_request_id'):
            req = order.garage_request_id
            if not self.env.user.has_group('garage_suite_pro.group_garage_purchase_approver'):
                raise AccessError(_('Only a Garage purchase approver can award a request-linked order.'))
            lines = order.order_line.filtered(lambda line: not line.display_type)
            if (req.state != 'approved' or len(lines) != 1 or lines.product_id != req.product_id
                    or lines.product_uom_id._compute_quantity(lines.product_qty, req.uom_id) > req.quantity
                    or req.order_ids.filtered(lambda other: other != order and other.state in ('purchase', 'done'))):
                raise ValidationError(_('Award at most one quote for the approved part and quantity.'))

    def button_confirm(self):
        self._check_garage_award()
        return super().button_confirm()

    def button_approve(self, force=False):
        self._check_garage_award()
        return super().button_approve(force=force)


class Capacity(models.TransientModel):
    _name = 'garage.capacity.report'
    _description = 'Garage Employee Capacity and Productivity'

    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)
    employee_id = fields.Many2one('hr.employee', required=True, domain="[('company_id', '=', company_id)]")
    date_from = fields.Date(required=True, default=lambda self: fields.Date.context_today(self).replace(day=1))
    date_to = fields.Date(required=True, default=fields.Date.context_today)
    available_hours = fields.Float(readonly=True)
    assigned_hours = fields.Float(readonly=True)
    actual_hours = fields.Float(readonly=True)
    completed_tasks = fields.Integer(readonly=True)
    productivity = fields.Float(readonly=True, digits=(16, 2))
    has_working_hours = fields.Boolean(readonly=True)
    calculated = fields.Boolean(readonly=True)

    def action_calculate(self):
        self.ensure_one()
        self.check_access('write')
        if self.company_id not in self.env.companies or self.employee_id.company_id != self.company_id:
            raise AccessError(_('Choose an employee in an authorized company.'))
        if self.date_to < self.date_from:
            raise ValidationError(_('The reporting end date must follow the start date.'))
        employee = self.employee_id.sudo()
        if not employee.user_id:
            raise ValidationError(_('Link this employee to a technician user first.'))
        calendar = employee.resource_calendar_id or self.company_id.resource_calendar_id
        if not calendar:
            raise ValidationError(_('Configure working hours for this employee.'))
        import pytz
        zone = pytz.timezone(calendar.tz or 'UTC')
        start = zone.localize(datetime.combine(self.date_from, time.min)).astimezone(timezone.utc)
        stop = zone.localize(datetime.combine(self.date_to + timedelta(days=1), time.min)).astimezone(timezone.utc)
        intervals = calendar._work_intervals_batch(start, stop, resources=employee.resource_id)[employee.resource_id.id]
        available = sum((end - begin).total_seconds() / 3600 for begin, end, _meta in intervals)
        lower, upper = start.replace(tzinfo=None), stop.replace(tzinfo=None)

        def interval_hours(begin, end):
            return (min(end, upper) - max(begin, lower)).total_seconds() / 3600

        tasks = self.env['garage.workshop.task'].search([
            ('employee_id', '=', employee.id), ('company_id', '=', self.company_id.id), ('state', 'in', ['scheduled', 'working', 'done']),
            ('planned_start', '<', upper), ('planned_end', '>', lower),
        ])
        time_entries = self.env['garage.job.time.entry'].search([
            ('technician_id', '=', employee.user_id.id), ('company_id', '=', self.company_id.id),
            ('start', '<', upper), ('end', '>', lower),
        ])
        completed = self.env['garage.workshop.task'].search_count([
            ('employee_id', '=', employee.id), ('company_id', '=', self.company_id.id), ('state', '=', 'done'),
            ('completed_at', '>=', lower), ('completed_at', '<', upper),
        ])
        actual = sum(interval_hours(entry.start, entry.end) for entry in time_entries)
        self.write({
            'available_hours': available,
            'assigned_hours': sum(interval_hours(task.planned_start, task.planned_end) for task in tasks),
            'actual_hours': actual, 'completed_tasks': completed,
            'productivity': 100 * actual / available if available else 0,
            'has_working_hours': bool(available), 'calculated': True,
        })
        return {'type': 'ir.actions.act_window', 'res_model': self._name, 'res_id': self.id, 'target': 'new', 'views': [(False, 'form')]}


class VendorBill(models.Model):
    _inherit = 'account.move'

    def _post(self, soft=True):
        posted = super()._post(soft=soft)
        lines = posted.filtered(lambda move: move.move_type == 'in_invoice').invoice_line_ids.purchase_line_id
        lines = lines.filtered(lambda line: line.order_id.garage_request_id and line.product_id.is_storable).sudo()
        lines.order_id.garage_request_id._lock_requests()
        for line in lines:
            billed = sum(
                item.product_uom_id._compute_quantity(item.quantity, line.product_uom_id)
                * (1 if item.move_id.move_type == 'in_invoice' else -1)
                for item in line.invoice_lines
                if item.move_id.state == 'posted' and item.move_id.move_type in ('in_invoice', 'in_refund')
            )
            if line.product_uom_id.compare(billed, line.qty_received) > 0:
                raise ValidationError(_('Vendor bills against Garage purchase requests cannot exceed the accepted receipt quantity.'))
        return posted


class MarketingMailing(models.Model):
    _inherit = 'mailing.mailing'

    garage_campaign_company_id = fields.Many2one('res.company', string='Garage Campaign Company', ondelete='restrict', index=True)

    @api.constrains('garage_campaign_company_id', 'mailing_model_id')
    def _check_garage_audience(self):
        for mailing in self.filtered('garage_campaign_company_id'):
            if mailing.mailing_model_real != 'res.partner':
                raise ValidationError(_('Garage campaigns must target Contacts so consent can be checked at sending time.'))

    def write(self, vals):
        if 'garage_campaign_company_id' in vals and any(
            mailing.garage_campaign_company_id and mailing.garage_campaign_company_id.id != vals['garage_campaign_company_id']
            for mailing in self
        ):
            raise ValidationError(_('Keep the original company and consent policy for a Garage campaign.'))
        return super().write(vals)

    def _get_recipients_domain(self):
        domain = super()._get_recipients_domain()
        if self.garage_campaign_company_id:
            if self.mailing_model_real != 'res.partner':
                raise ValidationError(_('Garage campaign recipients must be Contacts.'))
            domain &= Domain('is_garage_customer', '=', True) & Domain('garage_marketing_consent', '=', True)
            domain &= Domain('company_id', '=', self.garage_campaign_company_id.id)
        return domain
