from odoo import api, fields, models, _
from odoo.exceptions import AccessError, ValidationError
from odoo.tools import SQL


class GarageContract(models.Model):
    _name = 'garage.service.contract'
    _description = 'Garage Warranty, AMC or Fleet Contract'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_end, id'
    _check_company_auto = True

    name = fields.Char(default='New', readonly=True, copy=False, index=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company, index=True)
    currency_id = fields.Many2one(related='company_id.currency_id')
    customer_id = fields.Many2one('res.partner', required=True, check_company=True, ondelete='restrict', tracking=True)
    vehicle_ids = fields.Many2many('garage.vehicle', required=True, check_company=True)
    kind = fields.Selection([('warranty', 'Warranty'), ('amc', 'Annual Maintenance'), ('fleet', 'Fleet')], required=True, tracking=True)
    date_start = fields.Date(required=True)
    date_end = fields.Date(required=True, index=True)
    visit_limit = fields.Integer(required=True, default=1)
    coverage_limit = fields.Monetary(required=True)
    contract_value = fields.Monetary(help='Contract revenue agreed commercially; not a posted accounting balance.')
    terms = fields.Text(required=True)
    renewed_from_id = fields.Many2one('garage.service.contract', check_company=True, ondelete='restrict', readonly=True, copy=False)
    state = fields.Selection([('draft', 'Draft'), ('active', 'Active'), ('closed', 'Closed')], default='draft', required=True, copy=False, tracking=True)
    entitlement_ids = fields.One2many('garage.contract.entitlement', 'contract_id', readonly=True)
    committed_visits = fields.Integer(compute='_compute_balances', store=True)
    committed_coverage = fields.Monetary(compute='_compute_balances', store=True)
    service_cost = fields.Monetary(compute='_compute_balances', store=True)
    operating_contribution = fields.Monetary(compute='_compute_balances', store=True)

    @api.depends('entitlement_ids.state', 'entitlement_ids.amount', 'entitlement_ids.job_id.service_cost', 'contract_value')
    def _compute_balances(self):
        for contract in self:
            committed = contract.entitlement_ids.filtered(lambda item: item.state in ('approved', 'consumed'))
            contract.committed_visits = len(committed)
            contract.committed_coverage = sum(committed.mapped('amount'))
            contract.service_cost = sum(committed.filtered(lambda item: item.state == 'consumed').mapped('job_id.service_cost'))
            contract.operating_contribution = contract.contract_value - contract.service_cost

    @api.constrains('customer_id', 'vehicle_ids', 'date_start', 'date_end', 'visit_limit', 'coverage_limit', 'contract_value')
    def _validate_terms(self):
        for contract in self:
            if (not contract.vehicle_ids
                    or any(vehicle.customer_id.commercial_partner_id != contract.customer_id.commercial_partner_id for vehicle in contract.vehicle_ids)
                    or contract.date_end < contract.date_start or contract.visit_limit < 1
                    or contract.coverage_limit < 0 or contract.contract_value < 0):
                raise ValidationError(_('Check the dates, limits and ownership of the covered vehicles.'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('state', 'draft') != 'draft' or 'renewed_from_id' in vals:
                raise AccessError(_('Use the contract workflow to activate or renew.'))
            vals.update(state='draft', renewed_from_id=False, entitlement_ids=[])
            company = self.env['res.company'].browse(vals.get('company_id')) or self.env.company
            vals['name'] = self.env['ir.sequence'].with_company(company).next_by_code('garage.service.contract')
        return super().create(vals_list)

    def _lock_cover(self):
        self.flush_recordset(['write_date'])
        for contract_id in sorted(self.ids):
            self.env.cr.execute(SQL('UPDATE garage_service_contract SET write_date = write_date WHERE id = %s', contract_id))

    def write(self, vals):
        if {'state', 'name', 'renewed_from_id'} & vals.keys():
            raise AccessError(_('Use the contract workflow buttons.'))
        self._lock_cover()
        if set(vals) - {'activity_ids', 'message_follower_ids'} and self.filtered(lambda item: item.state != 'draft'):
            raise ValidationError(_('Keep activated contract terms and renew them on a new contract.'))
        return super().write(vals)

    def action_activate(self):
        self.check_access('write')
        self._lock_cover()
        if any(item.state != 'draft' for item in self):
            raise ValidationError(_('Only draft contracts can be activated.'))
        self._validate_terms()
        super().write({'state': 'active'})

    def action_close(self):
        self.check_access('write')
        self._lock_cover()
        if any(item.state != 'active' for item in self) or self.entitlement_ids.filtered(lambda item: item.state == 'approved'):
            raise ValidationError(_('Resolve approved entitlements before closing an active contract.'))
        super().write({'state': 'closed'})

    def action_renew(self):
        self.ensure_one()
        self.check_access('write')
        self._lock_cover()
        if self.state not in ('closed', 'active'):
            raise ValidationError(_('Only activated contracts can be renewed.'))
        renewed = self.search([('renewed_from_id', '=', self.id)], limit=1)
        if not renewed:
            from datetime import timedelta

            start = self.date_end + timedelta(days=1)
            renewed = self.copy({'date_start': start, 'date_end': start + (self.date_end - self.date_start)})
            super(GarageContract, renewed).write({'renewed_from_id': self.id})
        return {'type': 'ir.actions.act_window', 'res_model': self._name, 'res_id': renewed.id, 'views': [(False, 'form')]}


class Entitlement(models.Model):
    _name = 'garage.contract.entitlement'
    _description = 'Workshop Contract Entitlement'
    _inherit = ['mail.thread']
    _rec_name = 'job_id'
    _check_company_auto = True

    contract_id = fields.Many2one('garage.service.contract', required=True, check_company=True, ondelete='restrict', index=True)
    company_id = fields.Many2one(related='contract_id.company_id', store=True, index=True)
    currency_id = fields.Many2one(related='contract_id.currency_id')
    job_id = fields.Many2one('garage.job.card', required=True, check_company=True, ondelete='restrict', index=True)
    amount = fields.Monetary(required=True, tracking=True)
    scope = fields.Text(required=True)
    state = fields.Selection([('draft', 'Draft'), ('approved', 'Approved'), ('consumed', 'Consumed'), ('cancelled', 'Cancelled')], default='draft', required=True, copy=False, tracking=True)
    approver_id = fields.Many2one('res.users', readonly=True, copy=False)
    approved_at = fields.Datetime(readonly=True, copy=False)
    cancellation_reason = fields.Text(copy=False)
    _job_unique = models.Constraint('UNIQUE(job_id)', 'Only one entitlement is allowed per job card.')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('state', 'draft') != 'draft' or {'approver_id', 'approved_at'} & vals.keys():
                raise AccessError(_('Approval evidence comes from the entitlement workflow.'))
            vals.update(state='draft', approver_id=False, approved_at=False)
        return super().create(vals_list)

    def write(self, vals):
        if {'state', 'approver_id', 'approved_at', 'job_id', 'contract_id'} & vals.keys():
            raise AccessError(_('Use the entitlement workflow and keep its original references.'))
        if set(vals) - {'cancellation_reason', 'message_follower_ids'} and self.filtered(lambda item: item.state != 'draft'):
            raise ValidationError(_('Approved entitlement scope is retained.'))
        return super().write(vals)

    def action_approve(self):
        self.check_access('write')
        self.contract_id.check_access('write')
        self.contract_id._lock_cover()
        for item in self:
            contract, job = item.contract_id, item.job_id
            job.check_access('read')
            if (item.state != 'draft' or contract.state != 'active' or job.state in ('ready', 'delivered', 'closed', 'cancelled')
                    or job.vehicle_id not in contract.vehicle_ids
                    or job.customer_id.commercial_partner_id != contract.customer_id.commercial_partner_id
                    or not contract.date_start <= fields.Date.to_date(job.date) <= contract.date_end or item.amount < 0
                    or not item.scope.strip()):
                raise ValidationError(_('The job is outside the current customer, vehicle or date entitlement.'))
            commitments = self.search([('contract_id', '=', contract.id), ('state', 'in', ['approved', 'consumed'])])
            if (len(commitments) >= contract.visit_limit
                    or contract.currency_id.compare_amounts(sum(commitments.mapped('amount')) + item.amount, contract.coverage_limit) > 0):
                raise ValidationError(_('This authorization exceeds the contract entitlement. Obtain separate customer approval for uncovered scope.'))
            super(Entitlement, item).write({'state': 'approved', 'approver_id': self.env.user.id, 'approved_at': fields.Datetime.now()})

    def action_consume(self):
        self.check_access('write')
        self.contract_id.check_access('write')
        self.contract_id._lock_cover()
        if any(item.state != 'approved' or item.job_id.state != 'closed' for item in self):
            raise ValidationError(_('Only approved entitlements on closed jobs can be consumed.'))
        super().write({'state': 'consumed'})

    def action_cancel(self):
        self.check_access('write')
        self.contract_id.check_access('write')
        self.contract_id._lock_cover()
        if any(item.state not in ('draft', 'approved') or not (item.cancellation_reason or '').strip() for item in self):
            raise ValidationError(_('Record why the unused entitlement is being cancelled.'))
        super().write({'state': 'cancelled'})


class Claim(models.Model):
    _name = 'garage.insurance.claim'
    _description = 'Workshop Insurance Claim'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'
    _check_company_auto = True

    name = fields.Char(required=True, tracking=True, index=True)
    company_id = fields.Many2one(related='job_id.company_id', store=True, index=True)
    currency_id = fields.Many2one(related='job_id.currency_id')
    job_id = fields.Many2one('garage.job.card', required=True, check_company=True, ondelete='restrict', index=True)
    insurer_id = fields.Many2one('res.partner', required=True, check_company=True, ondelete='restrict')
    policy_reference = fields.Char(required=True)
    surveyor_id = fields.Many2one('res.partner', check_company=True, ondelete='restrict')
    estimate_id = fields.Many2one('sale.order', required=True, check_company=True, ondelete='restrict')
    previous_claim_id = fields.Many2one('garage.insurance.claim', check_company=True, ondelete='restrict')
    assessment = fields.Text(required=True)
    approval_evidence = fields.Text(copy=False)
    insurer_share = fields.Monetary(required=True, tracking=True)
    customer_share = fields.Monetary(required=True, tracking=True)
    deductible = fields.Monetary()
    depreciation = fields.Monetary()
    payment_id = fields.Many2one('account.payment', check_company=True, ondelete='restrict', copy=False)
    settled_amount = fields.Monetary(readonly=True, copy=False)
    outstanding = fields.Monetary(compute='_compute_outstanding', store=True)
    state = fields.Selection([('draft', 'Draft'), ('submitted', 'Submitted'), ('approved', 'Approved'), ('settled', 'Settled')], default='draft', required=True, copy=False, tracking=True)
    approved_at = fields.Datetime(readonly=True, copy=False)
    approved_by = fields.Many2one('res.users', readonly=True, copy=False)
    _estimate_unique = models.Constraint('UNIQUE(estimate_id)', 'An estimate version already has a claim.')
    _payment_unique = models.Constraint('UNIQUE(payment_id)', 'This payment is already recorded for another claim.')

    @api.depends('insurer_share', 'settled_amount')
    def _compute_outstanding(self):
        for claim in self:
            claim.outstanding = claim.insurer_share - claim.settled_amount

    @api.constrains('job_id', 'estimate_id', 'insurer_id', 'previous_claim_id', 'insurer_share', 'customer_share', 'deductible', 'depreciation')
    def _validate_claim(self):
        if self._has_cycle('previous_claim_id'):
            raise ValidationError(_('Claim supplements cannot form a cycle.'))
        for claim in self:
            if (claim.estimate_id.garage_job_id != claim.job_id or claim.estimate_id.currency_id != claim.currency_id
                    or min(claim.insurer_share, claim.customer_share, claim.deductible, claim.depreciation) < 0
                    or claim.currency_id.compare_amounts(claim.deductible + claim.depreciation, claim.customer_share) > 0):
                raise ValidationError(_('Check the estimate, currency and claim allocations.'))
            previous = claim.previous_claim_id
            if previous and (previous.job_id != claim.job_id or previous.insurer_id != claim.insurer_id
                             or previous.estimate_id.garage_version >= claim.estimate_id.garage_version
                             or previous.state not in ('approved', 'settled')):
                raise ValidationError(_('A supplement must reference an approved earlier revision for the same job and insurer.'))
            base_total = previous.estimate_id.amount_total if previous else 0
            if claim.currency_id.compare_amounts(claim.insurer_share + claim.customer_share, claim.estimate_id.amount_total - base_total):
                raise ValidationError(_('Allocate the full estimate, or the incremental amount for a supplement, between insurer and customer.'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('state', 'draft') != 'draft' or {'approved_at', 'approved_by', 'settled_amount'} & vals.keys():
                raise AccessError(_('Use the claims workflow to record approval and settlement.'))
            vals.update(state='draft', approved_at=False, approved_by=False, settled_amount=0)
        return super().create(vals_list)

    def _lock_claims(self):
        self.flush_recordset(['write_date'])
        for record_id in sorted(self.ids):
            self.env.cr.execute(SQL('UPDATE garage_insurance_claim SET write_date = write_date WHERE id = %s', record_id))

    def write(self, vals):
        if {'state', 'approved_at', 'approved_by', 'settled_amount'} & vals.keys():
            raise AccessError(_('Use the claims workflow buttons.'))
        self._lock_claims()
        if (set(vals) - {'approval_evidence', 'payment_id', 'message_follower_ids', 'activity_ids'}
                and self.filtered(lambda claim: claim.state != 'draft')):
            raise ValidationError(_('Submitted claim details are retained. Use a supplement for the next estimate.'))
        if ('payment_id' in vals and self.filtered(lambda claim: claim.state == 'settled')
                or 'approval_evidence' in vals and self.filtered(lambda claim: claim.state in ('approved', 'settled'))):
            raise ValidationError(_('Keep the approved evidence and settled payment reference.'))
        return super().write(vals)

    def action_submit(self):
        self.check_access('write')
        self._lock_claims()
        self._validate_claim()
        if any(claim.state != 'draft' or claim.estimate_id.garage_consent not in ('issued', 'approved') for claim in self):
            raise ValidationError(_('Submit a draft claim against an issued estimate.'))
        super().write({'state': 'submitted'})

    def action_approve(self):
        self.check_access('write')
        self._lock_claims()
        self._validate_claim()
        if any(claim.state != 'submitted' or not (claim.approval_evidence or '').strip() for claim in self):
            raise ValidationError(_('Record surveyor approval evidence for a submitted claim.'))
        super().write({'state': 'approved', 'approved_at': fields.Datetime.now(), 'approved_by': self.env.user.id})

    def action_settle(self):
        self.check_access('write')
        if not self.env.user.has_group('account.group_account_invoice'):
            raise AccessError(_('Only a user with invoicing rights can verify a claim settlement.'))
        self._lock_claims()
        for claim in self:
            payment = claim.payment_id
            payment.check_access('read')
            if (claim.state != 'approved' or not payment or payment.state != 'paid' or payment.payment_type != 'inbound'
                    or payment.partner_id.commercial_partner_id != claim.insurer_id.commercial_partner_id
                    or payment.company_id != claim.company_id or payment.currency_id != claim.currency_id
                    or claim.currency_id.compare_amounts(payment.amount, claim.insurer_share)):
                raise ValidationError(_('Select the paid insurer receipt matching the company, currency and full insurer share.'))
            super(Claim, claim).write({'state': 'settled', 'settled_amount': payment.amount})


class GarageJob(models.Model):
    _inherit = 'garage.job.card'

    def _check_state_transition(self, target):
        result = super()._check_state_transition(target)
        if target == 'in_progress':
            claims = self.env['garage.insurance.claim'].sudo().search([('job_id', 'in', self.ids)])
            for job in self & claims.job_id.with_env(self.env):
                current = job._approved_estimate()
                if not claims.filtered(lambda claim: claim.job_id == job and claim.estimate_id == current and claim.state in ('approved', 'settled')):
                    raise ValidationError(_('Obtain surveyor approval for the current estimate before starting or resuming this insured visit.'))
        return result
