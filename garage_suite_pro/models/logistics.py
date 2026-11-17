from odoo import api, fields, models, _
from odoo.exceptions import AccessError, ValidationError
from odoo.tools import SQL


class VehicleTransport(models.Model):
    _name = 'garage.vehicle.transport'
    _description = 'Garage Vehicle Pickup and Delivery'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _check_company_auto = True
    _order = 'scheduled_at desc'

    name = fields.Char(readonly=True, default='New', copy=False, index=True)
    company_id = fields.Many2one(related='job_id.company_id', store=True, index=True)
    job_id = fields.Many2one('garage.job.card', required=True, check_company=True, ondelete='restrict')
    driver_id = fields.Many2one('hr.employee', required=True, check_company=True, ondelete='restrict')
    kind = fields.Selection([('pickup', 'Pickup'), ('delivery', 'Delivery')], required=True)
    scheduled_at = fields.Datetime(required=True)
    address = fields.Text(required=True)
    evidence = fields.Text()
    recipient = fields.Char()
    completed_at = fields.Datetime(readonly=True, copy=False)
    completed_by = fields.Many2one('res.users', readonly=True, copy=False)
    cancellation_reason = fields.Text()
    state = fields.Selection([
        ('scheduled', 'Scheduled'), ('transit', 'In Transit'),
        ('done', 'Completed'), ('cancelled', 'Cancelled'),
    ], required=True, default='scheduled', tracking=True, copy=False)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('state', 'scheduled') != 'scheduled' or {'completed_at', 'completed_by'} & vals.keys():
                raise AccessError(_('Use the transport workflow to record completion.'))
            vals.update(state='scheduled', completed_at=False, completed_by=False,
                        name=self.env['ir.sequence'].next_by_code('garage.vehicle.transport'))
        trips = super().create(vals_list)
        trips.job_id.check_access('read')
        return trips

    def _lock_trips(self):
        self.flush_recordset(['write_date'])
        for trip_id in sorted(self.ids):
            self.env.cr.execute(SQL('UPDATE garage_vehicle_transport SET write_date = write_date WHERE id = %s', trip_id))

    def write(self, vals):
        if {'name', 'state', 'job_id', 'completed_at', 'completed_by'} & vals.keys():
            raise AccessError(_('Use the transport workflow and preserve its job reference.'))
        self._lock_trips()
        substantive = set(vals) - {'activity_ids', 'message_follower_ids'}
        if (substantive and any(trip.state in ('done', 'cancelled') for trip in self)
                or substantive - {'evidence', 'recipient', 'cancellation_reason'} and self.filtered(lambda trip: trip.state != 'scheduled')):
            raise ValidationError(_('Keep the original schedule or evidence once the trip progresses.'))
        return super().write(vals)

    def action_dispatch(self):
        self.check_access('write')
        self._lock_trips()
        for trip in self:
            trip.job_id.check_access('read')
            if trip.state != 'scheduled' or (trip.kind == 'delivery' and trip.job_id.state not in ('delivered', 'closed')):
                raise ValidationError(_('Schedule the trip and complete the Garage handover before dispatching a delivery.'))
            if trip.kind == 'pickup' and trip.job_id.state != 'draft':
                raise ValidationError(_('Dispatch a pickup before the job leaves Draft.'))
        super().write({'state': 'transit'})

    def action_complete(self):
        self.check_access('write')
        self._lock_trips()
        if any(trip.state != 'transit' or not (trip.recipient or '').strip() or not (trip.evidence or '').strip() for trip in self):
            raise ValidationError(_('Record the recipient and custody evidence for an in-transit vehicle.'))
        super().write({'state': 'done', 'completed_at': fields.Datetime.now(), 'completed_by': self.env.user.id})

    def action_cancel(self):
        self.check_access('write')
        self._lock_trips()
        if any(trip.state != 'scheduled' or not (trip.cancellation_reason or '').strip() for trip in self):
            raise ValidationError(_('Record the reason before cancelling a scheduled trip.'))
        super().write({'state': 'cancelled'})


class GarageJob(models.Model):
    _inherit = 'garage.job.card'

    garage_equipment_ids = fields.Many2many('maintenance.equipment', string='Workshop Equipment', check_company=True, groups='garage_suite_pro.group_garage_planner')
