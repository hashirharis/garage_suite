from datetime import datetime, time

import pytz
from dateutil.relativedelta import relativedelta

from odoo import api, fields, models, _


class TechnicianContribution(models.Model):
    _name = 'garage.technician.contribution'
    _description = 'Technician Labour Contribution'
    _auto = False
    _rec_name = 'job_id'
    _order = 'date desc, id desc'

    company_id = fields.Many2one('res.company', readonly=True)
    currency_id = fields.Many2one('res.currency', readonly=True)
    technician_id = fields.Many2one('res.users', readonly=True)
    job_id = fields.Many2one('garage.job.card', readonly=True)
    product_id = fields.Many2one('product.product', readonly=True)
    date = fields.Datetime(string='Labour Start', readonly=True)
    hours = fields.Float(readonly=True)
    allocated_revenue = fields.Monetary(string='Allocated Net Labour Revenue', readonly=True)
    direct_cost = fields.Monetary(string='Snapshotted Labour Cost', readonly=True)
    contribution = fields.Monetary(string='Direct Labour Contribution', readonly=True)

    @property
    def _table_query(self):
        return """
            WITH billed AS (
                SELECT garage_job_id, product_id, SUM(garage_revenue) AS net
                  FROM account_move_line
                 WHERE garage_job_id IS NOT NULL AND garage_line_kind = 'labour'
                 GROUP BY garage_job_id, product_id
            ),
            logged AS (
                SELECT t.id, t.job_id, t.company_id, t.technician_id, t.start,
                       w.product_id, t.hours, t.labour_cost,
                       SUM(t.hours) OVER (PARTITION BY t.job_id, w.product_id) AS operation_hours
                  FROM garage_job_time_entry t
                  JOIN garage_job_card_line w ON w.id = t.operation_line_id
                 WHERE t.hours > 0 AND t."end" IS NOT NULL
            ),
            allocation AS (
                SELECT l.*, c.currency_id,
                       COALESCE(b.net, 0) * l.hours / l.operation_hours AS allocated_revenue
                  FROM logged l
                  JOIN res_company c ON c.id = l.company_id
                  LEFT JOIN billed b ON b.garage_job_id = l.job_id AND b.product_id = l.product_id
            )
            SELECT id, company_id, currency_id, technician_id, job_id, product_id, start AS date,
                   hours, allocated_revenue, COALESCE(labour_cost, 0) AS direct_cost,
                   allocated_revenue - COALESCE(labour_cost, 0) AS contribution
              FROM allocation
        """


class GarageDashboard(models.Model):
    _inherit = 'garage.job.card'

    def _dashboard_workspaces(self, cards, date_domain, today):
        workspaces = super()._dashboard_workspaces(cards, date_domain, today)
        user = self.env.user
        now = fields.Datetime.to_string(fields.Datetime.now())
        today_str = fields.Date.to_string(today)
        month_end = fields.Date.to_string(fields.Date.end_of(today, 'month'))

        def count(key, label, model, domain, description, icon, tone):
            return {
                'key': key, 'label': label, 'model': model, 'domain': domain,
                'count': self.env[model].search_count(domain), 'description': description,
                'icon': icon, 'tone': tone,
            }

        if user.has_group('garage_suite_pro.group_garage_planner'):
            model = 'garage.workshop.task'
            workspaces.append({'key': 'planning', 'label': _('Planning'), 'role': _('Workshop Planner'), 'cards': [
                count('draft_tasks', _('Tasks to schedule'), model, [('state', '=', 'draft')], _('Unscheduled workshop tasks'), 'fa-calendar', 'blue'),
                count('working_tasks', _('Tasks in progress'), model, [('state', '=', 'working')], _('Started work orders'), 'fa-wrench', 'teal'),
                count('overdue_tasks', _('Overdue tasks'), model, [('state', 'in', ['scheduled', 'working']), ('planned_end', '<', now)], _('Planned end has passed'), 'fa-clock-o', 'amber'),
            ]})
        if user.has_group('garage_suite_pro.group_garage_buyer'):
            model = 'garage.purchase.request'
            workspaces.append({'key': 'procurement', 'label': _('Purchasing'), 'role': _('Garage Purchasing'), 'cards': [
                count('purchase_submitted', _('Requests awaiting approval'), model, [('state', '=', 'submitted')], _('Submitted parts requirements'), 'fa-file-text-o', 'amber'),
                count('purchase_approved', _('Approved requests'), model, [('state', '=', 'approved')], _('Authorized purchasing requirements'), 'fa-check-circle-o', 'teal'),
            ]})
        if user.has_group('garage_suite_pro.group_garage_coverage') or user.has_group('garage_suite_pro.group_garage_executive'):
            workspaces.append({'key': 'coverage', 'label': _('Claims & Contracts'), 'role': _('Insurance and Contracts'), 'cards': [
                count('claims_open', _('Open insurer balances'), 'garage.insurance.claim', [('state', '=', 'approved'), ('outstanding', '>', 0)], _('Approved and not yet settled'), 'fa-shield', 'amber'),
                count('contracts_expiring', _('Contracts expiring this month'), 'garage.service.contract',
                      [('state', '=', 'active'), ('date_end', '>=', today_str), ('date_end', '<=', month_end)],
                      _('Active contracts reaching their end date'), 'fa-file-text-o', 'violet'),
            ]})
        return workspaces

    @api.model
    def get_dashboard(self, period='30'):
        payload = super().get_dashboard(period)
        job_model = self.env['garage.job.card']
        company = self.env.company
        base_domain = [('company_id', '=', company.id)]
        reception_domain = base_domain + payload['visit_domain']
        received, closed, on_time = (
            job_model.search_count(reception_domain + domain)
            for domain in ([], [('state', '=', 'closed')], [('state', '=', 'closed'), ('garage_on_time', '=', True)])
        )
        scheduled = job_model.search_count(reception_domain + [('state', '=', 'closed'), ('expected_delivery', '!=', False)])
        executive = self.env.user.has_group('garage_suite_pro.group_garage_executive')
        pro = {
            'company': company.name, 'currency': company.currency_id.name,
            'received': received, 'closed': closed, 'scheduled_closed': scheduled,
            'on_time_rate': round(on_time / scheduled * 100, 1) if scheduled else None,
            'reception_domain': reception_domain,
            'closed_domain': reception_domain + [('state', '=', 'closed')],
            'on_time_domain': reception_domain + [('state', '=', 'closed'), ('garage_on_time', '=', True)],
            'profitability': None,
        }
        if executive:
            pro['profitability'] = self._garage_profitability_snapshot(reception_domain, base_domain)
        payload['pro'] = pro
        return payload

    def _garage_profitability_snapshot(self, reception_domain, company_domain):
        profitable = [('state', 'in', ['ready', 'delivered', 'closed'])]
        aggregates = ['service_revenue:sum', 'service_cost:sum', 'service_margin:sum']
        profit_domain = reception_domain + profitable
        revenue, cost, margin = (value or 0 for value in self._read_group(profit_domain, aggregates=aggregates)[0])
        today = fields.Date.context_today(self)
        month = today.replace(day=1)
        zone = pytz.timezone(self.env.context.get('tz') or self.env.user.tz or 'UTC')

        def boundary(day):
            stamp = zone.localize(datetime.combine(day, time.min)).astimezone(pytz.UTC).replace(tzinfo=None)
            return fields.Datetime.to_string(stamp)

        months = []
        for offset in range(-11, 1):
            start = month + relativedelta(months=offset)
            end = start + relativedelta(months=1)
            domain = company_domain + profitable + [('date', '>=', boundary(start)), ('date', '<', boundary(end))]
            sales, expenses, contribution = (value or 0 for value in self._read_group(domain, aggregates=aggregates)[0])
            months.append({
                'date': str(start), 'domain': domain, 'revenue': sales, 'cost': expenses, 'margin': contribution,
            })
        return {
            'revenue': revenue, 'cost': cost, 'margin': margin,
            'margin_rate': round(margin / revenue * 100, 1) if revenue > 0 else None,
            'domain': profit_domain, 'months': months,
        }


class JobDeliveryPerformance(models.Model):
    _inherit = 'garage.job.card'

    garage_on_time = fields.Boolean(compute='_compute_garage_on_time', store=True)

    @api.depends('expected_delivery', 'delivered_at')
    def _compute_garage_on_time(self):
        for job in self:
            job.garage_on_time = bool(
                job.expected_delivery and job.delivered_at and job.delivered_at <= job.expected_delivery
            )
