from odoo import api, fields, models, Command, _
from odoo.exceptions import AccessError, ValidationError

PHASES = [('reception', 'Reception'), ('technical', 'Technical'), ('final', 'Final Quality'), ('delivery', 'Delivery')]


class Template(models.Model):
    _name = 'garage.inspection.template'
    _inherit = 'garage.master.mixin'
    _description = 'Inspection Template'
    phase = fields.Selection(PHASES, required=True)
    default_for_jobs = fields.Boolean()
    line_ids = fields.One2many('garage.inspection.template.line', 'template_id')


class TemplateLine(models.Model):
    _name = 'garage.inspection.template.line'
    _description = 'Inspection Template Check'
    _order = 'sequence,id'
    sequence = fields.Integer(default=10)
    template_id = fields.Many2one('garage.inspection.template', required=True, ondelete='cascade')
    company_id = fields.Many2one(related='template_id.company_id', store=True)
    name = fields.Char(required=True)
    mandatory = fields.Boolean(default=True)


class Inspection(models.Model):
    _name = 'garage.inspection'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'Job Inspection and Sign-off'
    _check_company_auto = True
    _rec_name = 'template_id'
    work_revision = fields.Integer(readonly=True)
    job_id = fields.Many2one('garage.job.card', required=True, check_company=True, ondelete='restrict')
    company_id = fields.Many2one(related='job_id.company_id', store=True)
    template_id = fields.Many2one('garage.inspection.template', required=True, check_company=True)
    phase = fields.Selection(PHASES, readonly=True)
    line_ids = fields.One2many('garage.inspection.line', 'inspection_id')
    state = fields.Selection([('draft', 'Draft'), ('signed', 'Passed and Signed'), ('void', 'Voided for Rework')], default='draft', required=True, tracking=True)
    signed_by = fields.Many2one('res.users', readonly=True)
    signed_at = fields.Datetime(readonly=True)
    remarks = fields.Text()

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            self.env['garage.job.card'].browse(vals['job_id'])._require_role('advisor')
            template = self.env['garage.inspection.template'].browse(vals['template_id'])
            vals.update(work_revision=self.env['garage.job.card'].browse(vals['job_id']).work_revision, state='draft', signed_by=False, signed_at=False, phase=template.phase,
                        line_ids=[Command.create({'name': l.name, 'mandatory': l.mandatory}) for l in template.line_ids])
        return super().create(vals_list)

    def _check_editor(self):
        for rec in self:
            if rec.work_revision != rec.job_id.work_revision:
                raise ValidationError(_('Retain inspection evidence from earlier work revisions.'))
            if self.env.su or self.env.user.has_group('garage_core.group_garage_manager'):
                continue
            role = 'quality' if rec.phase == 'final' else 'technician' if rec.phase == 'technical' else 'advisor'
            rec.job_id._require_role(role)
            if rec.phase == 'technical' and self.env.user not in rec.job_id.technician_ids:
                raise AccessError(_('Only an assigned technician may record technical inspection results.'))

    def _check_sign(self):
        self._check_editor()
        for rec in self:
            if rec.state != 'draft' or not rec.line_ids or any(not l.result for l in rec.line_ids) or any(l.result != 'pass' for l in rec.line_ids.filtered('mandatory')):
                raise ValidationError(_('All mandatory inspection checks must pass before sign-off.'))
            role = 'quality' if rec.phase == 'final' else 'technician' if rec.phase == 'technical' else 'advisor'
            rec.job_id._require_role(role)
            if rec.phase == 'final' and self.env.user in rec.job_id.technician_ids:
                raise AccessError(_('An assigned technician cannot sign the final quality inspection.'))
            if rec.phase == 'final' and rec.job_id.state != 'quality_check':
                raise ValidationError(_('Submit completed work for quality inspection first.'))
            if rec.phase == 'delivery' and rec.job_id.state != 'ready':
                raise ValidationError(_('Delivery checks follow final readiness.'))

    def action_sign(self):
        self.write({'state': 'signed'})

    def write(self, vals):
        if {'job_id', 'template_id', 'phase', 'signed_by', 'signed_at', 'work_revision'} & vals.keys():
            raise AccessError(_('Inspection references and signatures are protected.'))
        if any(i.state != 'draft' for i in self):
            raise ValidationError(_('Signed inspection evidence is immutable; create a new inspection for rework.'))
        if vals.get('state'):
            if vals['state'] != 'signed':
                raise AccessError(_('Use a permitted inspection sign-off action.'))
            self._check_sign()
            vals = dict(vals, signed_by=self.env.user.id, signed_at=fields.Datetime.now())
        return super().write(vals)

    def unlink(self):
        raise AccessError(_('Inspection evidence is retained.'))


class InspectionLine(models.Model):
    _name = 'garage.inspection.line'
    _description = 'Inspection Check Result'
    inspection_id = fields.Many2one('garage.inspection', required=True, ondelete='cascade')
    company_id = fields.Many2one(related='inspection_id.company_id', store=True)
    name = fields.Char(required=True)
    mandatory = fields.Boolean()
    result = fields.Selection([('pass', 'Pass'), ('fail', 'Fail'), ('attention', 'Attention Required')])
    remarks = fields.Text()
    photo = fields.Image(max_width=1920, max_height=1920)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if self.env['garage.inspection'].browse(vals.get('inspection_id')).state != 'draft':
                raise ValidationError(_('Signed inspection checks cannot be extended.'))
        return super().create(vals_list)

    def write(self, vals):
        self.inspection_id._check_editor()
        if {'name', 'mandatory', 'inspection_id'} & vals.keys() or any(l.inspection_id.state != 'draft' for l in self):
            raise AccessError(_('Inspection definitions and signed results are protected.'))
        return super().write(vals)

    def unlink(self):
        raise AccessError(_('Inspection snapshots are retained.'))
