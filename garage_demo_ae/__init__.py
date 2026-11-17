from odoo.addons.garage_demo_common.seed import seed_workshop


def post_init_hook(env):
    seed_workshop(env, 'ae')
