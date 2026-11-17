from odoo import api, fields, models, _
from odoo.exceptions import AccessError, ValidationError


class SaleOrder(models.Model):
    _inherit = 'sale.order'
    garage_job_id = fields.Many2one('garage.job.card', check_company=True, copy=False, index=True, ondelete='restrict')
    garage_version = fields.Integer(copy=False, readonly=True)
    garage_consent = fields.Selection([('draft', 'Draft'), ('issued', 'Issued'), ('approved', 'Approved'), ('rejected', 'Rejected')], default='draft', required=True, copy=False, tracking=True)
    garage_approver_id = fields.Many2one('res.partner', check_company=True, copy=False, tracking=True)
    garage_consent_evidence = fields.Text(copy=False, tracking=True)
    garage_consent_channel = fields.Selection([('signed', 'Signature'), ('email', 'Email'), ('phone', 'Recorded Phone Consent'), ('in_person', 'In Person')], copy=False)
    garage_recorded_by = fields.Many2one('res.users', readonly=True, copy=False)
    garage_recorded_at = fields.Datetime(readonly=True, copy=False)
    garage_response_note = fields.Text(copy=False)

    _garage_version_unique = models.Constraint('UNIQUE(garage_job_id, garage_version)', 'Estimate version already exists for this visit.')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('garage_job_id'):
                job = self.env['garage.job.card'].browse(vals['garage_job_id'])
                job._require_role('advisor')
                job.check_access('write')
                if job.state not in ('diagnosing', 'awaiting_approval', 'authorized', 'on_hold'):
                    raise ValidationError(_('Prepare an estimate during diagnosis, approval, or a recorded hold.'))
                self.env.cr.execute('SELECT id FROM garage_job_card WHERE id = %s FOR UPDATE', [job.id])
                latest = self.search([('garage_job_id', '=', job.id)], order='garage_version desc', limit=1)
                vals.update(garage_version=latest.garage_version + 1, garage_consent='draft', garage_recorded_by=False, garage_recorded_at=False)
                if vals.get('partner_id', job.customer_id.id) != job.customer_id.id or vals.get('company_id', job.company_id.id) != job.company_id.id:
                    raise ValidationError(_('Estimate customer and company must match the visit.'))
                vals.update(partner_id=job.customer_id.id, company_id=job.company_id.id)
        return super().create(vals_list)

    def _validate_garage_plan(self):
        for order in self.filtered('garage_job_id'):
            job = order.garage_job_id
            services = order.order_line.filtered(lambda l: l.product_id.type == 'service').product_id
            planned = job.line_ids.filtered(lambda l: not l.included_in_package).product_id | job.package_id.product_id
            if set(services.ids) != set(planned.ids):
                raise ValidationError(_('Service estimate products must match the job operations and package. Record additional operations before issuing the revision.'))
            for product in job.part_movement_ids.product_id:
                movements = job.part_movement_ids.filtered(lambda m: m.product_id == product)
                used_or_held = sum(movements.filtered(lambda m: m.kind == 'issue').mapped('quantity')) - sum(movements.filtered(lambda m: m.kind == 'return').mapped('quantity'))
                approved = sum(line.product_uom_id._compute_quantity(line.product_uom_qty, product.uom_id) for line in order.order_line.filtered(lambda l: l.product_id == product))
                if used_or_held > approved + 0.00001:
                    raise ValidationError(_('A revision must retain quantities already consumed or issued. Return unused material before reducing scope.'))

    def _garage_record_response(self, response):
        for order in self:
            order.garage_job_id._require_role('advisor')
            if order.garage_consent == response:
                continue
            if order.garage_consent != 'issued':
                raise ValidationError(_('Only an issued estimate can receive consent.'))
            latest = self.search([('garage_job_id', '=', order.garage_job_id.id)], order='garage_version desc', limit=1)
            if latest != order or (order.validity_date and order.validity_date < fields.Date.context_today(order)):
                raise ValidationError(_('The estimate is stale or expired. Issue the current version.'))
            if not order.garage_approver_id or order.garage_approver_id.commercial_partner_id != order.partner_id.commercial_partner_id:
                raise ValidationError(_('The approver must be the customer or an authorized contact of that customer.'))
            if not order.garage_consent_evidence or not order.garage_consent_channel:
                raise ValidationError(_('Record the consent channel and supporting evidence.'))
            order.write({'garage_consent': response})
            if response == 'approved':
                order.action_confirm()
                if order.garage_job_id.state == 'awaiting_approval':
                    order.garage_job_id.write({'state': 'authorized'})

    def action_garage_issue(self):
        for order in self:
            order.garage_job_id._require_role('advisor')
            if not order.garage_job_id or order.garage_consent != 'draft' or not order.order_line.filtered(lambda l: not l.display_type):
                raise ValidationError(_('Issue a nonempty draft garage estimate.'))
            if any(l.discount > order.company_id.garage_advisor_discount_limit for l in order.order_line) and not self.env.user.has_group('garage_core.group_garage_manager'):
                raise AccessError(_('This discount exceeds your configured advisor limit; a manager must issue the estimate.'))
            if not order.validity_date or order.validity_date < fields.Date.context_today(order):
                raise ValidationError(_('Set a valid estimate expiry date.'))
            order.write({'garage_consent': 'issued'})
            if order.garage_job_id.state in ('diagnosing', 'authorized'):
                order.garage_job_id.write({'state': 'awaiting_approval'})

    def action_garage_approve(self):
        self._garage_record_response('approved')

    def action_garage_reject(self):
        self._garage_record_response('rejected')

    def action_confirm(self):
        if any(o.garage_job_id and o.garage_consent != 'approved' for o in self):
            raise ValidationError(_('Garage estimates require recorded customer consent before confirmation.'))
        return super().action_confirm()

    def write(self, vals):
        for order in self.filtered('garage_job_id'):
            if 'garage_consent' in vals:
                order.garage_job_id._require_role('advisor')
                if order.garage_job_id.state not in ('diagnosing','awaiting_approval','authorized','on_hold'):
                    raise ValidationError(_('The visit is not accepting estimate changes or customer responses.'))
                if vals['garage_consent'] in ('issued', 'approved'):
                    order._validate_garage_plan()
                if vals['garage_consent'] == 'issued' and any(l.discount > order.company_id.garage_advisor_discount_limit for l in order.order_line) and not self.env.user.has_group('garage_core.group_garage_manager'):
                    raise AccessError(_('This estimate discount requires a manager.'))
                if vals['garage_consent'] == 'issued' and (order.garage_consent != 'draft' or not order.order_line or not order.validity_date or order.validity_date < fields.Date.context_today(order)):
                    raise ValidationError(_('Issue a nonempty draft with a valid expiry date.'))
                if vals['garage_consent'] not in ('issued', 'approved', 'rejected') or order.garage_consent in ('approved', 'rejected'):
                    raise ValidationError(_('Estimate consent transitions are immutable.'))
            if {'garage_job_id', 'garage_version', 'garage_recorded_by', 'garage_recorded_at'} & vals.keys():
                raise AccessError(_('Garage estimate references and audit fields are protected.'))
            content = {'partner_id','partner_invoice_id','partner_shipping_id','company_id','currency_id','pricelist_id','fiscal_position_id','order_line','validity_date','payment_term_id','note','signature','signed_by','signed_on'}
            if order.garage_consent != 'draft' and content & vals.keys():
                raise ValidationError(_('Issued estimate content is immutable. Prepare a revision.'))
            if vals.get('partner_id', order.garage_job_id.customer_id.id) != order.garage_job_id.customer_id.id:
                raise ValidationError(_('The quote customer must remain the service visit customer.'))
            if vals.get('state') == 'cancel':
                raise ValidationError(_('Retain the estimate version and record customer rejection or cancel the service visit with its audit reason.'))
            commercial = {'partner_id', 'company_id', 'currency_id', 'pricelist_id', 'fiscal_position_id', 'order_line', 'validity_date', 'garage_approver_id', 'garage_consent_channel', 'garage_consent_evidence'}
            if commercial & vals.keys():
                order.garage_job_id._require_role('advisor')
            if order.garage_consent in ('approved', 'rejected') and commercial & vals.keys():
                raise ValidationError(_('Retain this estimate version. Create a revision for changes.'))
            if 'garage_consent' in vals:
                order.garage_job_id._require_role('advisor')
                if order.garage_job_id.state not in ('diagnosing','awaiting_approval','authorized','on_hold'):
                    raise ValidationError(_('The visit is not accepting estimate changes or customer responses.'))
                allowed = {'draft': ['issued'], 'issued': ['approved', 'rejected']}
                if vals['garage_consent'] not in allowed.get(order.garage_consent, []):
                    raise ValidationError(_('Invalid consent transition.'))
                if vals['garage_consent'] in ('approved', 'rejected'):
                    # All public RPC writes follow the same evidence and freshness gates.
                    if not order.garage_approver_id or order.garage_approver_id.commercial_partner_id != order.partner_id.commercial_partner_id or not order.garage_consent_evidence or not order.garage_consent_channel:
                        raise ValidationError(_('Record an authorized customer approver, channel and evidence.'))
                    latest = self.search([('garage_job_id', '=', order.garage_job_id.id)], order='garage_version desc', limit=1)
                    if latest != order or (order.validity_date and order.validity_date < fields.Date.context_today(order)):
                        raise ValidationError(_('Only the current, valid estimate may receive consent.'))
                    vals = dict(vals, garage_recorded_by=self.env.user.id, garage_recorded_at=fields.Datetime.now())
            if order.garage_consent == 'approved' and vals.get('state') in ('draft', 'cancel'):
                raise ValidationError(_('Approved scope cannot be cancelled or reset. Reconcile through the visit.'))
        return super().write(vals)

    def unlink(self):
        if self.filtered('garage_job_id'):
            raise AccessError(_('Retain garage estimate versions for audit.'))
        return super().unlink()


class SaleLine(models.Model):
    _inherit = 'sale.order.line'
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            order = self.env['sale.order'].browse(vals.get('order_id'))
            if order.garage_job_id and order.garage_consent != 'draft':
                raise ValidationError(_('Issued estimate lines are frozen. Create a revision.'))
        return super().create(vals_list)

    def write(self, vals):
        commercial = {'order_id', 'product_id', 'product_uom_qty', 'product_uom_id', 'price_unit', 'discount', 'tax_ids', 'name', 'display_type'}
        if commercial & vals.keys() and any(l.order_id.garage_job_id and l.order_id.garage_consent != 'draft' for l in self):
            raise ValidationError(_('Issued estimate lines are frozen. Create a revision.'))
        return super().write(vals)

    def unlink(self):
        if any(l.order_id.garage_job_id and l.order_id.garage_consent != 'draft' for l in self):
            raise ValidationError(_('Retain issued estimate lines.'))
        return super().unlink()
