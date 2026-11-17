{'name': 'Garage Basic Reports',
 'version': '19.0.1.1.1',
 'author': 'Garage Suite',
 'license': 'LGPL-3',
 'category': 'Services/Garage',
 'depends': ['garage_service_billing', 'garage_crm'],
 'data': ['reports/documents.xml', 'views/reports.xml', 'security/ir.model.access.csv', 'views/export.xml'],
 'external_dependencies': {'python': ['xlsxwriter']},
 'installable': True}
