{
    'name': 'Garage Shared Core',
    'version': '19.0.2.0.0',
    'category': 'Services/Garage',
    'summary': 'Shared customer, vehicle and job reception foundation',
    'author': 'Garage Suite',
    'license': 'LGPL-3',
    'depends': ['base', 'mail'],
    'data': ['security/groups.xml', 'security/ir.model.access.csv',
             'security/rules.xml', 'data/sequences.xml',
             'views/partner_views.xml', 'views/vehicle_views.xml',
             'views/job_card_views.xml', 'views/menus.xml'],
    'installable': True,
}
