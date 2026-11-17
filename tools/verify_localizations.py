# Execute with: odoo shell -d garage_localization_test --no-http < tools/verify_localizations.py
# This creates synthetic companies and commits only in a disposable test database.
if not env.cr.dbname.endswith('_test'):
    raise RuntimeError('Use a disposable database whose name ends with _test.')
results = []
for code in ['bh', 'sa', 'ae', 'in']:
    country = env['res.country'].search([('code', '=', code.upper())], limit=1)
    company = env['res.company'].create({'name': 'Garage Test ' + code.upper(), 'country_id': country.id})
    chart = env['account.chart.template'].with_company(company)
    chart.try_loading(code, company, install_demo=False)
    taxes = env['account.tax'].with_company(company).with_context(active_test=False).search([('company_id', '=', company.id), ('type_tax_use', '=', 'sale')])
    journals = env['account.journal'].with_company(company).search([('company_id', '=', company.id), ('type', '=', 'sale')])
    assert taxes and journals, '%s: taxes=%s journals=%s' % (code, len(taxes), len(journals))
    results.append({'country': code.upper(), 'taxes': len(taxes), 'sales_journals': len(journals), 'currency': company.currency_id.name})
print('COUNTRY_CHART_RESULTS', results)
env.cr.commit()
