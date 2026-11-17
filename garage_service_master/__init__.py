from odoo.tools.convert import convert_file

from . import models


def pre_init_hook(env):
    # Upgrading Basic can install Masters without reloading the already installed
    # Core. Bring the foundation's role records and access grants forward before
    # Masters imports its ACLs. Reuse the Core XML IDs to preserve assignments.
    if env.ref('garage_core.group_garage_staff', raise_if_not_found=False):
        return
    references = {}
    for filename in (
        'security/groups.xml',
        'security/ir.model.access.csv',
        'views/partner_views.xml',
        'views/menus.xml',
    ):
        convert_file(env, 'garage_core', filename, references, mode='update')


def post_init_hook(env):
    for vehicle in env['garage.vehicle'].search([]):
        values = {}
        make = vehicle.make_id
        if not make and vehicle.make:
            make = env['garage.vehicle.make'].search([('name', '=', vehicle.make), ('company_id', '=', vehicle.company_id.id)], limit=1) or env['garage.vehicle.make'].create({'name': vehicle.make, 'company_id': vehicle.company_id.id})
            values['make_id'] = make.id
        model = vehicle.model_id
        if not model and vehicle.model and make:
            model = env['garage.vehicle.model'].search([('name', '=', vehicle.model), ('make_id', '=', make.id), ('company_id', '=', vehicle.company_id.id)], limit=1) or env['garage.vehicle.model'].create({'name': vehicle.model, 'make_id': make.id, 'company_id': vehicle.company_id.id})
            values['model_id'] = model.id
        if not vehicle.variant_id and vehicle.variant and model:
            variant = env['garage.vehicle.variant'].search([('name', '=', vehicle.variant), ('model_id', '=', model.id), ('company_id', '=', vehicle.company_id.id)], limit=1) or env['garage.vehicle.variant'].create({'name': vehicle.variant, 'model_id': model.id, 'company_id': vehicle.company_id.id})
            values['variant_id'] = variant.id
        if values:
            vehicle.write(values)
