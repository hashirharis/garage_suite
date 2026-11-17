from .seed import ProDemo


def post_init_hook(env):
    marker = 'garage_demo.pro_company_id'
    params = env['ir.config_parameter'].sudo()
    if not params.get_param(marker):
        fixture = ProDemo(env, 'in')
        fixture.populate()
        params.set_param(marker, fixture.company.id)
