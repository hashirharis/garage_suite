from odoo import api, fields, models, _
from odoo.exceptions import AccessError, ValidationError
from odoo.tools import SQL


class Part(models.Model):
    _inherit = 'product.template'

    garage_oem_reference = fields.Char(index=True)
    garage_aftermarket_reference = fields.Char(index=True)
    garage_part_brand = fields.Char(index=True)
    garage_part_manufacturer = fields.Char()
    garage_warranty_months = fields.Integer()
    garage_mrp = fields.Monetary(currency_field='currency_id')
    garage_alternative_ids = fields.Many2many('product.template', 'garage_part_alternative_rel', 'part_id', 'alternative_id', domain="[('garage_part', '=', True)]")
    garage_superseded_by_id = fields.Many2one('product.template', check_company=True, ondelete='restrict', domain="[('garage_part', '=', True)]")
    garage_fitment_ids = fields.One2many('garage.part.fitment', 'product_tmpl_id')

    @api.constrains('garage_warranty_months', 'garage_mrp', 'garage_alternative_ids', 'garage_superseded_by_id', 'garage_part', 'type', 'company_id')
    def _check_garage_catalogue(self):
        if self._has_cycle('garage_superseded_by_id'):
            raise ValidationError(_('Superseded part references cannot form a cycle.'))
        for part in self:
            alternatives = part.garage_alternative_ids
            if part.garage_warranty_months < 0 or part.garage_mrp < 0 or part in alternatives:
                raise ValidationError(_('Check the warranty, maximum price and alternative parts.'))
            for related in alternatives | part.garage_superseded_by_id:
                if not related.garage_part or related.company_id and related.company_id != part.company_id:
                    raise ValidationError(_('Use garage parts visible to the same company for cross-references.'))
            if part.garage_part and part.type != 'consu':
                raise ValidationError(_('Automotive parts must be configured as Goods.'))


class PartFitment(models.Model):
    _name = 'garage.part.fitment'
    _description = 'Verified Automotive Part Fitment'
    _rec_name = 'product_tmpl_id'
    _check_company_auto = True

    company_id = fields.Many2one('res.company', required=True, index=True, default=lambda self: self.env.company)
    product_tmpl_id = fields.Many2one('product.template', required=True, check_company=True, ondelete='cascade', index=True, domain="[('garage_part', '=', True)]")
    make_id = fields.Many2one('garage.vehicle.make', required=True, check_company=True, ondelete='restrict')
    model_id = fields.Many2one('garage.vehicle.model', required=True, check_company=True, ondelete='restrict')
    variant_id = fields.Many2one('garage.vehicle.variant', check_company=True, ondelete='restrict')
    year_from = fields.Integer()
    year_to = fields.Integer()
    engine_code = fields.Char(help='Exact engine code from the manufacturer catalogue.')
    fuel_type = fields.Selection(selection=lambda self: self.env['garage.vehicle']._fields['fuel_type']._description_selection(self.env))
    transmission = fields.Selection(selection=lambda self: self.env['garage.vehicle']._fields['transmission']._description_selection(self.env))
    evidence = fields.Char(required=True, help='Manufacturer or supplier catalogue and revision.')
    active = fields.Boolean(default=True)

    @api.constrains('make_id', 'model_id', 'variant_id', 'year_from', 'year_to', 'evidence', 'product_tmpl_id')
    def _check_fitment(self):
        for fitment in self:
            if (fitment.model_id.make_id != fitment.make_id
                    or fitment.variant_id and fitment.variant_id.model_id != fitment.model_id
                    or fitment.year_from < 0 or fitment.year_to < 0
                    or fitment.year_to and fitment.year_to < fitment.year_from
                    or not fitment.evidence.strip() or not fitment.product_tmpl_id.garage_part):
                raise ValidationError(_('Check the fitment hierarchy, year range, parts flag and catalogue evidence.'))


class GarageVehicle(models.Model):
    _inherit = 'garage.vehicle'

    garage_engine_code = fields.Char()

    def action_compatible_parts(self):
        self.ensure_one()
        self.check_access('read')
        if not self.make_id or not self.model_id:
            raise ValidationError(_('Set the vehicle’s manufacturer and model masters first.'))
        fitments = self.env['garage.part.fitment'].search([
            ('company_id', '=', self.company_id.id),
            ('make_id', '=', self.make_id.id), ('model_id', '=', self.model_id.id),
        ])
        year = self.manufacturing_year
        matches = fitments.filtered(lambda f: (
            (not f.variant_id or f.variant_id == self.variant_id)
            and (not f.year_from or year and f.year_from <= year)
            and (not f.year_to or year and year <= f.year_to)
            and (not f.fuel_type or f.fuel_type == self.fuel_type)
            and (not f.transmission or f.transmission == self.transmission)
            and (not f.engine_code or (self.garage_engine_code or '').strip().casefold() == f.engine_code.strip().casefold())
        ))
        action = self.env['ir.actions.actions']._for_xml_id('garage_suite_pro.action_parts')
        action.update(domain=[('garage_part', '=', True), ('id', 'in', matches.product_tmpl_id.ids)],
                      context={'create': False, 'allowed_company_ids': self.company_id.ids})
        return action


class SaleLine(models.Model):
    _inherit = 'sale.order.line'

    def _action_launch_stock_rule(self, *args, **kwargs):
        # Garage issues stock against actual workshop movements. Confirming consent must not create a second delivery.
        retail_lines = self.filtered(lambda line: not line.order_id.garage_job_id)
        return super(SaleLine, retail_lines)._action_launch_stock_rule(*args, **kwargs)


class Company(models.Model):
    _inherit = 'res.company'

    garage_stock_warehouse_id = fields.Many2one('stock.warehouse', check_company=True)
    garage_workshop_location_id = fields.Many2one('stock.location', check_company=True, domain="[('usage', '=', 'internal'), ('company_id', '=', id)]")
    garage_consumption_location_id = fields.Many2one('stock.location', check_company=True, domain="[('usage', '=', 'production'), ('company_id', '=', id)]")

    @api.constrains('garage_stock_warehouse_id', 'garage_workshop_location_id', 'garage_consumption_location_id')
    def _check_garage_stock_configuration(self):
        for company in self:
            warehouse = company.garage_stock_warehouse_id
            workshop = company.garage_workshop_location_id
            consumption = company.garage_consumption_location_id
            if not (warehouse or workshop or consumption):
                continue
            if (not (warehouse and workshop and consumption)
                    or any(resource.company_id != company for resource in (warehouse, workshop, consumption))
                    or workshop.usage != 'internal' or consumption.usage != 'production'
                    or workshop == warehouse.lot_stock_id
                    or workshop.parent_path.startswith(warehouse.lot_stock_id.parent_path)
                    or warehouse.lot_stock_id.parent_path.startswith(workshop.parent_path)):
                raise ValidationError(_('Set a company warehouse, a separate internal workshop staging location, and a production consumption location.'))


class WorkshopReservation(models.Model):
    _name = 'garage.stock.reservation'
    _description = 'Workshop Stock Reservation'
    _rec_name = 'product_id'
    _check_company_auto = True

    job_id = fields.Many2one('garage.job.card', required=True, check_company=True, ondelete='restrict', index=True)
    company_id = fields.Many2one(related='job_id.company_id', store=True, index=True)
    product_id = fields.Many2one('product.product', required=True, check_company=True, ondelete='restrict', domain="[('garage_part', '=', True), ('is_storable', '=', True)]")
    quantity = fields.Float(required=True)
    move_id = fields.Many2one('stock.move', readonly=True, copy=False, ondelete='restrict', check_company=True)
    state = fields.Selection(related='move_id.state')
    cancel_reason = fields.Text()
    uom_id = fields.Many2one(related='product_id.uom_id')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('move_id'):
                raise ValidationError(_('The reservation action creates the stock move.'))
            vals['move_id'] = False
        records = super().create(vals_list)
        for record in records:
            record.job_id.check_access('read')
            if record.quantity <= 0:
                raise ValidationError(_('Reserve a positive quantity.'))
        return records

    def write(self, vals):
        if {'move_id', 'job_id', 'company_id'} & vals.keys() or (set(vals) - {'cancel_reason'} and self.filtered('move_id')):
            raise ValidationError(_('Keep the original reservation references.'))
        if 'quantity' in vals and vals['quantity'] <= 0:
            raise ValidationError(_('Reserve a positive quantity.'))
        return super().write(vals)

    def action_reserve(self):
        self.check_access('write')
        for item in self.sorted('job_id'):
            item.job_id._lock_garage_stock()
            if item.move_id:
                continue
            if item.job_id.state not in ('authorized', 'in_progress'):
                raise ValidationError(_('Reserve parts after work is authorized.'))
            product = item.product_id
            if not product.is_storable or not product.garage_part or product.tracking != 'none':
                raise ValidationError(_('Use untracked, stock-managed garage parts in workshop reservations.'))
            item.job_id._validate_garage_reserved_quantity(product, item.quantity)
            company = item.company_id
            warehouse = company.garage_stock_warehouse_id
            if not warehouse:
                raise ValidationError(_('Configure the workshop stock locations first.'))
            move = item.job_id.sudo()._create_garage_stock_move(product, item.quantity, warehouse.lot_stock_id, company.garage_workshop_location_id)
            super(WorkshopReservation, item).write({'move_id': move.id})

    def action_check_availability(self):
        self.check_access('write')
        for item in self.sorted('job_id'):
            item.job_id._lock_garage_stock()
            if item.move_id and item.state in ('confirmed', 'partially_available'):
                item.move_id.sudo()._action_assign()

    def action_cancel(self):
        self.check_access('write')
        for item in self.sorted('job_id'):
            item.job_id._lock_garage_stock()
            if not item.move_id or item.state in ('done', 'cancel') or not (item.cancel_reason or '').strip():
                raise ValidationError(_('Only open reservations can be cancelled with a reason.'))
            item.move_id.sudo()._action_cancel()


class GarageJob(models.Model):
    _inherit = 'garage.job.card'

    garage_stock_reservation_ids = fields.One2many('garage.stock.reservation', 'job_id', groups='stock.group_stock_user')

    def _lock_garage_stock(self):
        self.flush_recordset(['write_date'])
        for job in self.sorted('id'):
            self.env.cr.execute(SQL('UPDATE garage_job_card SET write_date = write_date WHERE id = %s', job.id))

    def _validate_garage_reserved_quantity(self, product, additional):
        self.ensure_one()
        order = self._approved_estimate()
        approved = sum(
            line.product_uom_id._compute_quantity(line.product_uom_qty, product.uom_id)
            for line in order.order_line.filtered(lambda line: line.product_id == product)
        )
        moves = self.part_movement_ids.filtered(lambda move: move.product_id == product)
        issued = sum(moves.filtered(lambda move: move.kind == 'issue').mapped('quantity'))
        returned = sum(moves.filtered(lambda move: move.kind == 'return').mapped('quantity'))
        pending = sum(self.sudo().garage_stock_reservation_ids.filtered(
            lambda item: item.product_id == product and item.move_id and item.state not in ('done', 'cancel')
        ).mapped('quantity'))
        if product.uom_id.compare(issued - returned + pending + additional, approved) > 0:
            raise ValidationError(_('Reservations and net issues cannot exceed approved scope.'))

    def _create_garage_stock_move(self, product, quantity, source, destination):
        self.ensure_one()
        move = self.env['stock.move'].with_company(self.company_id).create({
            'product_id': product.id, 'product_uom_qty': quantity,
            'product_uom': product.uom_id.id, 'location_id': source.id,
            'location_dest_id': destination.id, 'company_id': self.company_id.id,
            'garage_workshop_job_id': self.id,
        })
        move._action_confirm(merge=False)
        move._action_assign()
        return move

    def _check_state_transition(self, target):
        result = super()._check_state_transition(target)
        if target in ('ready', 'cancelled') and self.env['garage.stock.reservation'].sudo().search_count([
            ('job_id', 'in', self.ids), ('move_id', '!=', False), ('state', 'not in', ['done', 'cancel']),
        ]):
            raise ValidationError(_('Issue or cancel the remaining parts reservations before moving this job forward.'))
        return result


class StockMove(models.Model):
    _inherit = 'stock.move'

    garage_workshop_job_id = fields.Many2one('garage.job.card', readonly=True, check_company=True, copy=False, index=True, ondelete='restrict')
    garage_movement_id = fields.Many2one('garage.part.movement', readonly=True, check_company=True, copy=False, index=True, ondelete='restrict')
    _garage_movement_unique = models.Constraint('UNIQUE(garage_movement_id)', 'A workshop movement already has a stock move.')

    @api.model_create_multi
    def create(self, vals_list):
        moves = super().create(vals_list)
        if not self.env.su and moves.filtered('garage_workshop_job_id'):
            raise AccessError(_('Create workshop stock moves through the Garage reservation or movement workflow.'))
        return moves

    def write(self, vals):
        if not self.env.su and (
            {'garage_workshop_job_id', 'garage_movement_id'} & vals.keys() or self.filtered('garage_workshop_job_id')
        ):
            raise AccessError(_('Update workshop stock through the Garage reservation or movement workflow.'))
        return super().write(vals)

    def unlink(self):
        if self.filtered('garage_workshop_job_id'):
            raise AccessError(_('Keep workshop stock movement evidence.'))
        return super().unlink()


class StockMoveLine(models.Model):
    _inherit = 'stock.move.line'

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        if not self.env.su and lines.move_id.filtered('garage_workshop_job_id'):
            raise AccessError(_('Use the Garage workflow to add workshop stock move lines.'))
        return lines

    def write(self, vals):
        jobs = self.move_id.garage_workshop_job_id
        if not self.env.su and (jobs or self.env['stock.move'].browse(vals.get('move_id')).garage_workshop_job_id):
            raise AccessError(_('Use the Garage workflow to update workshop stock move lines.'))
        return super().write(vals)

    def unlink(self):
        if not self.env.su and self.move_id.garage_workshop_job_id:
            raise AccessError(_('Use the Garage workflow to remove unused reservations.'))
        return super().unlink()


class PartMovement(models.Model):
    _inherit = 'garage.part.movement'

    garage_reservation_id = fields.Many2one('garage.stock.reservation', check_company=True, ondelete='restrict', copy=False)
    garage_stock_move_ids = fields.One2many('stock.move', 'garage_movement_id', readonly=True, copy=False, groups='stock.group_stock_user')

    @api.model_create_multi
    def create(self, vals_list):
        jobs = self.env['garage.job.card'].browse([vals['job_id'] for vals in vals_list if vals.get('job_id')])
        jobs.check_access('read')
        jobs._lock_garage_stock()
        records = super().create(vals_list)
        for record in records:
            record._sync_garage_stock()
        return records

    def _sync_garage_stock(self):
        self.ensure_one()
        job = self.job_id
        company = job.company_id
        warehouse = company.garage_stock_warehouse_id
        reservation = self.garage_reservation_id
        if reservation and (self.kind != 'issue' or not warehouse or not self.product_id.is_storable):
            raise ValidationError(_('Only stock-managed issues can use a workshop reservation.'))
        if not warehouse or not self.product_id.is_storable:
            return
        if self.product_id.tracking != 'none':
            raise ValidationError(_('Lot- and serial-tracked parts require a lot-aware workshop workflow.'))
        # The Basic movement already authorized the issue/return/consume role and validated its quantity.
        secure_job = job.sudo().with_company(company)
        workshop = company.garage_workshop_location_id
        stock = warehouse.lot_stock_id
        if self.kind == 'issue' and reservation:
            reservation.check_access('read')
            if (reservation.job_id != job or reservation.product_id != self.product_id
                    or reservation.state != 'assigned'
                    or self.uom_id.compare(reservation.quantity, self.quantity)):
                raise ValidationError(_('Issue the fully reserved quantity from this job and part.'))
            move = reservation.sudo().move_id
        else:
            if self.kind == 'issue':
                job._validate_garage_reserved_quantity(self.product_id, 0)
            destination = {'issue': workshop, 'return': stock, 'consume': company.garage_consumption_location_id}[self.kind]
            move = secure_job._create_garage_stock_move(self.product_id, self.quantity, stock if self.kind == 'issue' else workshop, destination)
        if move.state != 'assigned' or self.uom_id.compare(move.quantity, self.quantity):
            raise ValidationError(_('Insufficient available stock for this workshop movement.'))
        move.picked = True
        move._action_done()
        move.sudo().write({'garage_movement_id': self.id})
