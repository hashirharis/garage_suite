import re

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, ValidationError


def normalize_identifier(value):
    return re.sub(r'[^A-Z0-9]', '', (value or '').upper()) or False


class GarageVehicle(models.Model):
    _name = 'garage.vehicle'
    _description = 'Garage Vehicle'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _check_company_auto = True
    _order = 'id desc'

    name = fields.Char(default='New', required=True, readonly=True, copy=False, index=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda s: s.env.company, index=True)
    customer_id = fields.Many2one('res.partner', required=True, check_company=True, tracking=True, ondelete='restrict')
    registration_number = fields.Char(tracking=True, index=True)
    vin = fields.Char(string='VIN / Chassis Number', tracking=True, index=True)
    registration_key = fields.Char(compute='_compute_keys', store=True)
    vin_key = fields.Char(compute='_compute_keys', store=True)
    engine_number = fields.Char()
    make = fields.Char(required=True)
    model = fields.Char(required=True)
    variant = fields.Char()
    manufacturing_year = fields.Integer()
    registration_year = fields.Integer()
    fuel_type = fields.Selection([('petrol', 'Petrol'), ('diesel', 'Diesel'), ('cng', 'CNG'), ('hybrid', 'Hybrid'), ('electric', 'Electric'), ('other', 'Other')])
    transmission = fields.Selection([(v, v.upper()) for v in ('manual', 'amt', 'cvt', 'dct', 'at')])
    category = fields.Selection([('car', 'Car'), ('suv', 'SUV'), ('bike', 'Bike'), ('commercial', 'Commercial')])
    engine_capacity = fields.Float(string='Engine Capacity (cc)')
    insurance_expiry = fields.Date()
    pollution_expiry = fields.Date(string='Pollution Certificate Expiry')
    service_interval_km = fields.Integer()
    service_interval_months = fields.Integer()
    notes = fields.Text()
    change_reason = fields.Char(string='Identity / Ownership Change Reason', copy=False)
    job_card_ids = fields.One2many('garage.job.card', 'vehicle_id', string='Service Visits')
    history_ids = fields.One2many('garage.vehicle.history', 'vehicle_id', string='Identity and Ownership History')
    odometer = fields.Float(compute='_compute_odometer', string='Latest Odometer (km)')

    _vin_unique = models.Constraint('UNIQUE(company_id, vin_key)', 'VIN already exists in this company.')
    _registration_unique = models.Constraint('UNIQUE(company_id, registration_key)', 'Registration already exists in this company.')
    _name_unique = models.Constraint('UNIQUE(company_id, name)', 'Vehicle reference must be unique.')

    @api.depends('vin', 'registration_number')
    def _compute_keys(self):
        for vehicle in self:
            vehicle.vin_key = normalize_identifier(vehicle.vin)
            vehicle.registration_key = normalize_identifier(vehicle.registration_number)

    @api.depends('job_card_ids.odometer')
    def _compute_odometer(self):
        for vehicle in self:
            vehicle.odometer = max(vehicle.job_card_ids.mapped('odometer'), default=0)

    @api.constrains('vin', 'registration_number', 'engine_capacity', 'service_interval_km', 'service_interval_months')
    def _check_vehicle(self):
        for vehicle in self:
            if not (vehicle.vin_key or vehicle.registration_key):
                raise ValidationError(_('Enter a registration number or VIN/chassis number.'))
            if min(vehicle.engine_capacity, vehicle.service_interval_km, vehicle.service_interval_months) < 0:
                raise ValidationError(_('Vehicle measurements and service intervals cannot be negative.'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if {'vin_key', 'registration_key'} & vals.keys():
                raise ValidationError(_('Normalized identifiers are generated automatically.'))
            if not (normalize_identifier(vals.get('vin')) or normalize_identifier(vals.get('registration_number'))):
                raise ValidationError(_('Enter a registration number or VIN/chassis number.'))
            vals['name'] = self.env['ir.sequence'].next_by_code('garage.vehicle') or 'New'
        records = super().create(vals_list)
        for record in records:
            record._record_identity('Initial registration')
        return records

    def _record_identity(self, reason):
        self.env['garage.vehicle.history'].sudo().create({
            'vehicle_id': self.id, 'customer_id': self.customer_id.id,
            'registration_number': self.registration_number, 'vin': self.vin,
            'reason': reason, 'actor_id': self.env.user.id,
            'changed_at': fields.Datetime.now(),
        })

    def write(self, vals):
        if {'vin_key', 'registration_key'} & vals.keys():
            raise ValidationError(_('Normalized identifiers are generated automatically.'))
        if 'name' in vals:
            raise ValidationError(_('Vehicle references cannot be changed.'))
        if 'company_id' in vals and any(v.company_id.id != vals['company_id'] for v in self):
            raise ValidationError(_('Vehicle company cannot be changed.'))
        identity = {'customer_id', 'registration_number', 'vin'}
        changed = self.filtered(lambda r: any(k in vals and vals[k] != (r[k].id if k == 'customer_id' else r[k]) for k in identity))
        if changed:
            if not self.env.user.has_group('garage_core.group_garage_manager'):
                raise AccessError(_('Only a garage manager can change vehicle identity or ownership.'))
            if not vals.get('change_reason', '').strip():
                raise ValidationError(_('Provide a reason with every identity or ownership change.'))
        result = super().write(vals)
        for record in changed:
            record._record_identity(vals['change_reason'])
        return result


class GarageVehicleHistory(models.Model):
    _name = 'garage.vehicle.history'
    _description = 'Vehicle Identity and Ownership Audit'
    _rec_name = 'vehicle_id'
    _order = 'id desc'

    vehicle_id = fields.Many2one('garage.vehicle', required=True, ondelete='restrict')
    company_id = fields.Many2one(related='vehicle_id.company_id', store=True)
    customer_id = fields.Many2one('res.partner', required=True, ondelete='restrict')
    registration_number = fields.Char()
    vin = fields.Char()
    reason = fields.Char(required=True)
    actor_id = fields.Many2one('res.users', required=True)
    changed_at = fields.Datetime(required=True)

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su:
            raise AccessError(_('Vehicle history is generated automatically.'))
        return super().create(vals_list)

    def write(self, vals):
        raise AccessError(_('Vehicle history is immutable.'))

    def unlink(self):
        raise AccessError(_('Vehicle history is immutable.'))
