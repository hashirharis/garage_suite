from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class Master(models.AbstractModel):
    _name = 'garage.master.mixin'
    _description = 'Garage Configurable Master'
    _check_company_auto = True
    _order = 'sequence, name, id'
    name = fields.Char(required=True, translate=True)
    code = fields.Char(index=True)
    active = fields.Boolean(default=True)
    sequence = fields.Integer(default=10)
    company_id = fields.Many2one('res.company', default=lambda s: s.env.company)


class Make(models.Model):
    _name = 'garage.vehicle.make'
    _inherit = 'garage.master.mixin'
    _description = 'Vehicle Manufacturer'


class VehicleModel(models.Model):
    _name = 'garage.vehicle.model'
    _inherit = 'garage.master.mixin'
    _description = 'Vehicle Model'
    make_id = fields.Many2one('garage.vehicle.make', required=True, check_company=True, ondelete='restrict')


class Variant(models.Model):
    _name = 'garage.vehicle.variant'
    _inherit = 'garage.master.mixin'
    _description = 'Vehicle Variant'
    model_id = fields.Many2one('garage.vehicle.model', required=True, check_company=True, ondelete='restrict')


class VehicleCategory(models.Model):
    _name = 'garage.vehicle.category'
    _inherit = 'garage.master.mixin'
    _description = 'Vehicle Category'


class ServiceCategory(models.Model):
    _name = 'garage.service.category'
    _inherit = 'garage.master.mixin'
    _description = 'Service Category'


class ServiceType(models.Model):
    _name = 'garage.service.type'
    _inherit = 'garage.master.mixin'
    _description = 'Service Type'


class Bay(models.Model):
    _name = 'garage.service.bay'
    _inherit = 'garage.master.mixin'
    _description = 'Workshop Bay'
    company_id = fields.Many2one('res.company', required=True, default=lambda s: s.env.company)


class Skill(models.Model):
    _name = 'garage.technician.skill'
    _inherit = 'garage.master.mixin'
    _description = 'Technician Skill'


class Operation(models.Model):
    _name = 'garage.service.operation'
    _inherit = 'garage.master.mixin'
    _description = 'Service Catalogue Operation'
    category_id = fields.Many2one('garage.service.category', check_company=True)
    product_id = fields.Many2one('product.product', required=True, check_company=True, ondelete='restrict', domain="[('type', '=', 'service')]")
    standard_hours = fields.Float(default=1)
    pricing = fields.Selection([('fixed', 'Fixed Price'), ('hourly', 'Hourly')], default='fixed', required=True)
    skill_ids = fields.Many2many('garage.technician.skill', check_company=True)
    warranty_days = fields.Integer()
    @api.constrains('product_id', 'standard_hours', 'warranty_days')
    def _check_service(self):
        for rec in self:
            if rec.product_id.type != 'service' or rec.standard_hours < 0 or rec.warranty_days < 0:
                raise ValidationError(_('Use a service product and nonnegative durations.'))


class LabourRate(models.Model):
    _name = 'garage.labour.rate'
    _inherit = 'garage.master.mixin'
    _description = 'Vehicle Specific Labour Rate'
    operation_id = fields.Many2one('garage.service.operation', required=True, check_company=True)
    make_id = fields.Many2one('garage.vehicle.make', check_company=True)
    model_id = fields.Many2one('garage.vehicle.model', check_company=True)
    currency_id = fields.Many2one(related='company_id.currency_id')
    rate = fields.Monetary(required=True)
    @api.constrains('rate', 'make_id', 'model_id')
    def _check_rate(self):
        for rec in self:
            if rec.rate < 0 or (rec.make_id and rec.model_id and rec.model_id.make_id != rec.make_id):
                raise ValidationError(_('Check the rate and vehicle manufacturer/model.'))


class ServicePackage(models.Model):
    _name = 'garage.service.package'
    _inherit = 'garage.master.mixin'
    _description = 'Service Package'
    product_id = fields.Many2one('product.product', required=True, check_company=True, domain="[('type', '=', 'service')]")
    operation_ids = fields.Many2many('garage.service.operation', check_company=True, string='Included Labour Operations')
    description = fields.Text()
    @api.constrains('product_id')
    def _check_product(self):
        if any(p.product_id.type != 'service' for p in self):
            raise ValidationError(_('Packages require a service product.'))


class HoldReason(models.Model):
    _name = 'garage.hold.reason'
    _inherit = 'garage.master.mixin'
    _description = 'Workshop Waiting Reason'
    category = fields.Selection([('parts', 'Waiting for Parts'), ('approval', 'Waiting for Approval'), ('other', 'Other')], required=True, default='other')
