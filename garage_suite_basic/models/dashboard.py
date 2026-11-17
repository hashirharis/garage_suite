from datetime import datetime, time, timedelta
import pytz

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, ValidationError
from odoo.addons.garage_core.models.job_card import JOB_STATES


class GarageJobCard(models.Model):
    _inherit = 'garage.job.card'

    @api.model
    def get_dashboard(self, period='30'):
        """One access-filtered source for metrics and their drill-down domains."""
        if not self.env.user.has_group('garage_core.group_garage_staff'):
            raise AccessError(_('Garage access is required.'))
        if period not in ('7', '30', '90', 'all'):
            raise ValidationError(_('Choose a supported dashboard period.'))
        now = fields.Datetime.now()
        date_domain = [] if period == 'all' else [('date', '>=', fields.Datetime.to_string(now - timedelta(days=int(period))))]
        open_domain = [('state', 'not in', ['closed', 'cancelled'])]
        overdue_domain = open_domain + [('expected_delivery', '<', fields.Datetime.to_string(now))]
        customer_domain = [('is_garage_customer', '=', True), '|', ('company_id', '=', False), ('company_id', 'in', self.env.companies.ids)]
        metrics = [
            ('visits', _('Service visits'), 'garage.job.card', date_domain, _('In selected period'), 'fa-file-text-o', 'blue'),
            ('open', _('Open job cards'), 'garage.job.card', open_domain, _('All active visits'), 'fa-wrench', 'teal'),
            ('overdue', _('Delivery overdue'), 'garage.job.card', overdue_domain, _('Expected delivery has passed'), 'fa-clock-o', 'amber'),
            ('vehicles', _('Registered vehicles'), 'garage.vehicle', [], _('Current vehicle registry'), 'fa-car', 'slate'),
            ('customers', _('Customers'), 'res.partner', customer_domain, _('Workshop customer profiles'), 'fa-users', 'violet'),
        ]
        today = fields.Date.context_today(self)
        tz = pytz.timezone(self.env.user.tz or 'UTC')
        day_start = tz.localize(datetime.combine(today, time.min)).astimezone(pytz.UTC).replace(tzinfo=None)
        day_end = tz.localize(datetime.combine(today + timedelta(days=1), time.min)).astimezone(pytz.UTC).replace(tzinfo=None)
        metrics += [
            ('received_today', _('Received today'), 'garage.job.card', [('date','>=',fields.Datetime.to_string(day_start)),('date','<',fields.Datetime.to_string(day_end))], _('Local reception date'), 'fa-calendar-check-o','blue'),
            ('repair', _('Under repair'), 'garage.job.card', [('state','=','in_progress')], _('Authorized work in progress'), 'fa-cogs','teal'),
            ('ready', _('Ready for delivery'), 'garage.job.card', [('state','=','ready')], _('Passed final quality checks'), 'fa-check-circle-o','teal'),
            ('approval', _('Awaiting approval'), 'garage.job.card', [('state','=','awaiting_approval')], _('Current estimate issued'), 'fa-pencil-square-o','amber'),
            ('parts', _('Waiting for parts'), 'garage.job.card', [('state','=','on_hold'),('hold_category','=','parts')], _('Material-related holds'), 'fa-cubes','amber'),
            ('repeat', _('Repeat / rework visits'), 'garage.job.card', date_domain + ['|',('source','=','repeat'),('work_revision','>',0)], _('In selected period'), 'fa-repeat','slate'),
        ]
        cards = [{'key': key, 'label': label, 'model': model, 'domain': domain,
                  'count': self.env[model].search_count(domain), 'description': description,
                  'icon': icon, 'tone': tone}
                 for key, label, model, domain, description, icon, tone in metrics]
        pipeline = []
        for key, label in JOB_STATES:
            domain = date_domain + [('state', '=', key)]
            count = self.search_count(domain)
            if count or key in ('draft', 'diagnosing', 'cancelled'):
                pipeline.append({'key': key, 'label': label, 'count': count, 'domain': domain})
        visits = self.search(date_domain, limit=8, order='date desc, id desc')
        recent = [{'id': job.id, 'name': job.name, 'customer': job.customer_id.display_name,
                   'vehicle': job.registration_at_reception or job.vin_at_reception or job.vehicle_id.name,
                   'advisor': job.advisor_id.name, 'state': dict(JOB_STATES)[job.state],
                   'state_key': job.state, 'expected_delivery': fields.Datetime.to_string(job.expected_delivery) if job.expected_delivery else False}
                  for job in visits]
        finance = []
        if self.env.user.has_group('garage_core.group_garage_cashier') or self.env.user.has_group('garage_core.group_garage_owner'):
            company = self.env.company
            invoice_domain = [('company_id','=',company.id),('garage_job_id','!=',False),('state','=','posted'),('invoice_date','=',str(today)),('move_type','in',['out_invoice','out_refund'])]
            invoices = self.env['account.move'].search(invoice_domain)
            payment_domain = [('company_id','=',company.id),('partner_type','=','customer'),('date','=',str(today)),('state','in',['in_process','paid']),('garage_payment','=',True)]
            payments = self.env['account.payment'].search(payment_domain)
            collected = sum(p.currency_id._convert(p.amount, company.currency_id, company, p.date) * (1 if p.payment_type == 'inbound' else -1) for p in payments)
            outstanding_domain = [('company_id','=',company.id),('garage_job_id','!=',False),('state','=','posted'),('move_type','=','out_invoice'),('amount_residual','>',0)]
            for key,label,model,domain,value in [('revenue',_("Today's net service revenue"),'account.move',invoice_domain,sum(invoices.mapped('amount_untaxed_signed'))),('collected',_("Today's collections"),'account.payment',payment_domain,collected),('outstanding',_('Outstanding service invoices'),'account.move',outstanding_domain,sum(self.env['account.move'].search(outstanding_domain).mapped('amount_residual_signed')))]:
                finance.append({'key':key,'label':label,'model':model,'domain':domain,'value':value,'currency':company.currency_id.name,'digits':company.currency_id.decimal_places,'description':company.name})
        # Seven local calendar buckets. This chart always shows the last week.
        trend = []
        for offset in range(6, -1, -1):
            day = today - timedelta(days=offset)
            start = tz.localize(datetime.combine(day, time.min)).astimezone(pytz.UTC)
            stop = tz.localize(datetime.combine(day + timedelta(days=1), time.min)).astimezone(pytz.UTC)
            domain = [('date', '>=', fields.Datetime.to_string(start)), ('date', '<', fields.Datetime.to_string(stop))]
            trend.append({'date': str(day), 'count': self.search_count(domain), 'domain': domain})
        return {'trend': trend, 'cards': cards, 'finance': finance, 'pipeline': pipeline, 'recent': recent,
                'workspaces': self._dashboard_workspaces(cards, date_domain, today),
                'list_views': {
                    'sale.order': self.env.ref('garage_suite_basic.service_estimate_list').id,
                    'account.move': self.env.ref('garage_suite_basic.service_invoice_list').id,
                    'account.payment': self.env.ref('garage_suite_basic.service_payment_list').id,
                },
                'visit_domain': date_domain, 'total': cards[0]['count'],
                'company': ', '.join(self.env.companies.mapped('name')),
                'updated_at': fields.Datetime.to_string(now)}

    def _dashboard_workspaces(self, cards, date_domain, today):
        indexed = {card['key']: card for card in cards}
        jobs = 'garage.job.card'
        user = self.env.user

        def metric(key, label, model, domain, description, icon, aggregate=None):
            records = self.env[model]
            value = (records._read_group(domain, aggregates=[aggregate + ':sum'])[0][0] or 0) if aggregate else records.search_count(domain)
            return {'key': key, 'label': label, 'model': model, 'domain': domain,
                    'count': round(value, 1), 'description': description, 'icon': icon, 'tone': 'teal'}

        def workspace(key, label, role, card_keys, extra):
            return {'key': key, 'label': label, 'role': role,
                    'cards': [indexed[k] for k in card_keys] + extra}

        def has(*roles):
            return any(user.has_group('garage_core.group_garage_' + role) for role in roles)

        workspaces = []
        if has('receptionist', 'user'):
            workspaces.append(workspace('reception', _('Front Desk'), _('Reception'), ['received_today', 'ready', 'overdue'], [
                metric('bookings', _('Upcoming appointments'), 'garage.appointment', [('state', '=', 'booked'), ('start', '>=', fields.Datetime.to_string(fields.Datetime.now()))], _('Booked and awaiting arrival'), 'fa-calendar'),
                metric('arrived', _('Awaiting job card'), 'garage.appointment', [('state', '=', 'arrived')], _('Arrived appointments'), 'fa-car'),
            ]))
        if has('user'):
            workspaces.append(workspace('advisor', _('Service Desk'), _('Service Advisor'), ['approval', 'ready', 'overdue'], [
                metric('my_jobs', _('My open visits'), jobs, [('advisor_id', '=', user.id), ('state', 'not in', ['closed', 'cancelled', 'delivered'])], _('Assigned to you'), 'fa-user'),
                metric('followups', _('Follow-ups due'), 'garage.service.reminder', [('due_date', '<=', str(today)), ('state', '=', 'pending'), ('assigned_id', '=', user.id)], _('Assigned to you'), 'fa-phone'),
            ]))
        if has('technician'):
            my_jobs = [('technician_ids', 'in', [user.id])]
            time_domain = [('technician_id', '=', user.id)]
            time_period = [(('start' if name == 'date' else name), operator, value) for name, operator, value in date_domain]
            workspaces.append(workspace('technician', _('My Work'), _('Technician'), [], [
                metric('assigned', _('Assigned active visits'), jobs, my_jobs + [('state', 'in', ['authorized', 'in_progress', 'on_hold'])], _('Your authorized, running and held visits'), 'fa-wrench'),
                metric('timers', _('Running timers'), 'garage.job.time.entry', time_domain + [('end', '=', False)], _('Your open labour entries'), 'fa-clock-o'),
                metric('hours', _('Hours logged'), 'garage.job.time.entry', time_domain + time_period, _('Actual hours in selected period'), 'fa-hourglass-half', 'hours'),
            ]))
        if has('quality'):
            workspaces.append(workspace('quality', _('Quality'), _('Quality Inspector'), ['ready', 'repeat'], [
                metric('quality_queue', _('Awaiting quality check'), jobs, [('state', '=', 'quality_check')], _('Visits submitted for final review'), 'fa-check-square-o'),
                metric('failed_checks', _('Final inspections with failed checks'), 'garage.inspection', [('phase', '=', 'final'), ('state', '=', 'draft'), ('job_id.state', '=', 'quality_check'), ('line_ids', 'any', [('result', '=', 'fail')])], _('Draft final inspections with a failed item'), 'fa-exclamation-circle'),
            ]))
        if has('storekeeper'):
            workspaces.append(workspace('parts', _('Parts Desk'), _('Parts Storekeeper'), ['parts'], [
                metric(kind, label, 'garage.part.movement',
                       [('kind', '=', kind)] + [('recorded_at', op, value) for _, op, value in date_domain],
                       _('Movement entries in selected period'), 'fa-cubes')
                for kind, label in [('issue', _('Issues')), ('consume', _('Consumption')), ('return', _('Returns'))]
            ]))
        if has('cashier', 'owner'):
            workspaces.append(workspace('billing', _('Billing'), _('Service Billing'), [], [
                metric('draft_invoices', _('Draft service invoices'), 'account.move', [('garage_job_id', '!=', False), ('move_type', '=', 'out_invoice'), ('state', '=', 'draft')], _('Awaiting posting'), 'fa-file-text-o'),
                metric('unpaid_invoices', _('Open service balances'), 'account.move', [('garage_job_id', '!=', False), ('move_type', '=', 'out_invoice'), ('state', '=', 'posted'), ('amount_residual', '>', 0)], _('Posted invoices with a balance'), 'fa-credit-card'),
            ]))
        if has('manager', 'owner'):
            workspaces.insert(0, workspace('management', _('Management'), _('Workshop Management'), ['open', 'overdue', 'ready', 'approval', 'parts', 'repeat'], [
                metric('closed', _('Completed visits'), jobs, date_domain + [('state', '=', 'closed')], _('Closed visits received in selected period'), 'fa-check-circle-o'),
                metric('actual_hours', _('Actual labour hours'), jobs, date_domain, _('Hours on visits received in selected period'), 'fa-clock-o', 'actual_hours'),
            ]))
        if not workspaces:
            workspaces.append(workspace('overview', _('Workshop'), _('Workshop Reader'), ['open', 'overdue', 'ready', 'vehicles', 'customers'], []))
        return workspaces
