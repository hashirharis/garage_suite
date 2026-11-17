from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class Vehicle(models.Model):
    _inherit = 'garage.vehicle'
    make_id = fields.Many2one('garage.vehicle.make', string='Manufacturer Master', check_company=True, ondelete='restrict')
    model_id = fields.Many2one('garage.vehicle.model', string='Model Master', check_company=True, ondelete='restrict')
    variant_id = fields.Many2one('garage.vehicle.variant', string='Variant Master', check_company=True, ondelete='restrict')
    category_id = fields.Many2one('garage.vehicle.category', string='Category Master', check_company=True)

    @api.onchange('make_id', 'model_id', 'variant_id')
    def _onchange_masters(self):
        if self.make_id:
            self.make = self.make_id.name
        if self.model_id:
            self.model = self.model_id.name
        if self.variant_id:
            self.variant = self.variant_id.name

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            for key, model, text in [('make_id', 'garage.vehicle.make', 'make'), ('model_id', 'garage.vehicle.model', 'model'), ('variant_id', 'garage.vehicle.variant', 'variant')]:
                if vals.get(key):
                    vals[text] = self.env[model].browse(vals[key]).name
        return super().create(vals_list)

    def write(self, vals):
        vals = dict(vals)
        for key, model, text in [('make_id', 'garage.vehicle.make', 'make'), ('model_id', 'garage.vehicle.model', 'model'), ('variant_id', 'garage.vehicle.variant', 'variant')]:
            if vals.get(key):
                vals[text] = self.env[model].browse(vals[key]).name
        return super().write(vals)

    @api.constrains('make_id', 'model_id', 'variant_id', 'make', 'model', 'variant')
    def _check_master_links(self):
        for rec in self:
            if any(rec[key] and rec[text] != rec[key].name for key, text in [('make_id','make'),('model_id','model'),('variant_id','variant')]):
                raise ValidationError(_('Vehicle specification labels must match the selected master records.'))
            if rec.model_id and rec.make_id != rec.model_id.make_id:
                raise ValidationError(_('Vehicle model must belong to its manufacturer.'))
            if rec.variant_id and rec.model_id != rec.variant_id.model_id:
                raise ValidationError(_('Vehicle variant must belong to its model.'))


class Job(models.Model):
    _inherit = 'garage.job.card'
    service_type_id = fields.Many2one('garage.service.type', string='Service Type Master', check_company=True)
    bay_id = fields.Many2one('garage.service.bay', check_company=True)
    package_id = fields.Many2one('garage.service.package', check_company=True)


class JobLine(models.Model):
    _inherit = 'garage.job.card.line'
    operation_id = fields.Many2one('garage.service.operation', string='Catalogue Operation', check_company=True)
    product_id = fields.Many2one('product.product', check_company=True, domain="[('type', '=', 'service')]")
    included_in_package = fields.Boolean()

    @api.onchange('operation_id')
    def _onchange_operation(self):
        if self.operation_id:
            op = self.operation_id
            self.name, self.product_id, self.planned_hours = op.name, op.product_id, op.standard_hours
            rates = self.env['garage.labour.rate'].search([('operation_id', '=', op.id), ('company_id', '=', self.job_id.company_id.id), '|', ('make_id', '=', False), ('make_id', '=', self.job_id.vehicle_id.make_id.id), '|', ('model_id', '=', False), ('model_id', '=', self.job_id.vehicle_id.model_id.id)])
            rates = rates.sorted(lambda r: (bool(r.model_id), bool(r.make_id), -r.sequence), reverse=True)
            unit_rate = rates[:1].rate if rates else op.product_id.lst_price
            self.labour_charge = unit_rate * (op.standard_hours if op.pricing == 'hourly' else 1)


class Users(models.Model):
    _inherit = 'res.users'
    garage_hourly_cost = fields.Float(string='Workshop Hourly Cost', groups='garage_core.group_garage_manager')
    garage_skill_ids = fields.Many2many('garage.technician.skill', string='Workshop Skills')


class Product(models.Model):
    _inherit = 'product.template'
    garage_service_category_id = fields.Many2one('garage.service.category', check_company=True)
    garage_part = fields.Boolean(string='Workshop Part / Consumable')


class JobLineSecurity(models.Model):
    _inherit = 'garage.job.card.line'

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            job = self.env['garage.job.card'].browse(vals.get('job_id'))
            if hasattr(job, '_require_role'):
                job._require_role('advisor')
            if job.state not in ('draft', 'diagnosing', 'on_hold'):
                raise ValidationError(_('Revise operational scope only during reception, diagnosis or a recorded hold.'))
            if vals.get('included_in_package'):
                op = self.env['garage.service.operation'].browse(vals.get('operation_id'))
                if not job.package_id or op not in job.package_id.operation_ids:
                    raise ValidationError(_('Only configured package operations may be marked included.'))
        return super().create(vals_list)

    def write(self, vals):
        for line in self:
            if hasattr(line.job_id, '_require_role'):
                line.job_id._require_role('advisor')
            if hasattr(line.job_id, '_current_estimate') and line.job_id._current_estimate().garage_consent in ('issued', 'approved'):
                raise ValidationError(_('Create a new estimate revision before changing approved job operations.'))
            if line.job_id.state not in ('draft', 'diagnosing', 'on_hold'):
                raise ValidationError(_('Record a hold before changing operational scope.'))
        return super().write(vals)


    @api.constrains('operation_id', 'product_id', 'included_in_package', 'job_id')
    def _check_operation_definition(self):
        for line in self:
            if line.product_id and line.product_id.type != 'service':
                raise ValidationError(_('Labour operations use service products; add parts on the estimate.'))
            if line.operation_id and line.product_id != line.operation_id.product_id:
                raise ValidationError(_('Use the service product defined by the catalogue operation.'))
            if line.included_in_package and (not line.job_id.package_id or line.operation_id not in line.job_id.package_id.operation_ids):
                raise ValidationError(_('Only configured package operations can be marked included.'))
