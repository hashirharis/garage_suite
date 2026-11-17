from odoo import http
from odoo.tools import format_datetime
from odoo.http import request
from odoo.addons.portal.controllers.portal import CustomerPortal, pager as portal_pager


class GaragePortal(CustomerPortal):

    @http.route(['/my/garage-visits', '/my/garage-visits/page/<int:page>'], type='http', auth='user', website=True)
    def garage_visits(self, page=1, **kwargs):
        partner = request.env.user.partner_id
        # Scope to the recorded visit customer. Registry ownership changes never grant access to prior visits.
        company_ids = request.website.company_id.ids
        domain = [('customer_id', '=', partner.id), ('company_id', 'in', company_ids)]
        jobs = request.env['garage.job.card'].sudo()
        pager = portal_pager(url='/my/garage-visits', total=jobs.search_count(domain), page=page, step=20)
        rows = jobs.search(domain, order='date desc, id desc', offset=pager['offset'], limit=20).read([
            'name', 'registration_at_reception', 'vin_at_reception', 'date', 'state', 'expected_delivery',
        ])
        states = dict(jobs._fields['state']._description_selection(request.env))
        for row in rows:
            row['status'] = states[row.pop('state')]
            row['date'] = format_datetime(request.env, row['date'])
            if row['expected_delivery']:
                row['expected_delivery'] = format_datetime(request.env, row['expected_delivery'])
        values = self._prepare_portal_layout_values()
        values.update(visits=rows, pager=pager, page_name='garage_visits')
        return request.render('garage_pro_online.portal_my_garage_visits', values)
