from datetime import datetime, time, timedelta

import pytz
from dateutil.relativedelta import relativedelta

from odoo import Command, fields
from odoo.tools import SQL

from .profiles import PROFILES


def _stamp(records, **dates):
    """Set historical timestamps on newly seeded records after workflow actions."""
    if not records:
        return
    records.flush_recordset()
    records.env.cr.execute(SQL(
        'UPDATE %s SET %s WHERE id IN %s',
        SQL.identifier(records._table),
        SQL(', ').join(SQL('%s = %s', SQL.identifier(key), value) for key, value in dates.items()),
        tuple(records.ids),
    ))
    records.invalidate_recordset(list(dates), flush=False)
    records.modified(list(dates))


def seed_workshop(env, code):
    marker = 'garage_demo.seeded_company_' + code
    parameters = env['ir.config_parameter'].sudo()
    if parameters.get_param(marker):
        return
    fixture = WorkshopDemo(env, code)
    fixture.populate()
    parameters.set_param(marker, fixture.company.id)


class WorkshopDemo:

    def __init__(self, env, code):
        self.profile = profile = PROFILES[code]
        self.code = code.upper()
        country = env['res.country'].search([('code', '=', self.code)], limit=1)
        state = env.ref(profile['state_xmlid']) if profile.get('state_xmlid') else False
        company = env['res.company'].create({
            'name': self._company_name(country),
            'country_id': country.id,
            'state_id': state and state.id,
            'city': profile['cities'][0],
            'street': 'Demo Workshop District',
        })
        self.company = company
        env = env(su=True, context={
            'allowed_company_ids': company.ids,
            'tz': profile['timezone'],
            'tracking_disable': True,
            'mail_create_nosubscribe': True,
            'mail_create_nolog': True,
            'no_reset_password': True,
        })
        self.company = company.with_env(env)
        chart = env['account.chart.template']
        chart.try_loading(code, self.company, install_demo=False)
        if template := profile.get('sale_tax_template'):
            # The native India chart ships this GST group and its components inactive.
            tax = chart.ref(template)
            (tax | tax.with_context(active_test=False).children_tax_ids).write({'active': True})
            self.company.account_sale_tax_id = tax
        self.env = env
        self.manager = self._staff('Manager', 'manager')
        self.technician = self._staff('Technician', 'technician', garage_hourly_cost=profile['prices'][2])
        self.inspector = self._staff('Quality Inspector', 'quality')
        self.env = env(user=self.manager.id, su=True)
        self.company = company.with_env(self.env)
        self.today = fields.Date.context_today(self.company)

    def _company_name(self, country):
        return f'Garage Demo - {country.name}'

    def _staff(self, name, role, **values):
        return self.env['res.users'].create({
            'name': f'{self.code} Demo {name}',
            'login': f'garage-demo-{self.code.lower()}-{role}@example.invalid',
            'tz': self.profile['timezone'],
            'company_id': self.company.id,
            'company_ids': [Command.set(self.company.ids)],
            'group_ids': [Command.set(self.env.ref(f'garage_core.group_garage_{role}').ids)],
            **values,
        })

    def _create(self, model, **values):
        return self.env[model].create({'company_id': self.company.id, **values})

    def _fleet_identity(self, index):
        return (
            f'DEMO-{self.code}-{index + 1:04d}',
            f'GSD{self.code}{index + 1:012d}',
            f'garage-{self.code.lower()}-customer-{index + 1}@example.invalid',
        )

    def _fleet(self):
        makes = {}
        categories = {}
        fleet = []
        for index, (make, model, variant, fuel, transmission, category) in enumerate(self.profile['vehicles']):
            if make not in makes:
                makes[make] = self._create('garage.vehicle.make', name=make)
            if category not in categories:
                categories[category] = self._create('garage.vehicle.category', name=category.title())
            model_record = self._create('garage.vehicle.model', name=model, make_id=makes[make].id)
            variant_record = self._create('garage.vehicle.variant', name=variant, model_id=model_record.id)
            plate, vin, email = self._fleet_identity(index)
            partner = self._create(
                'res.partner', name=self.profile['customers'][index],
                city=self.profile['cities'][index % len(self.profile['cities'])],
                country_id=self.company.country_id.id, state_id=self.company.state_id.id,
                email=email,
                customer_rank=1, is_garage_customer=True, garage_service_consent=True,
                garage_notes='Synthetic customer for workshop demonstrations.',
            )
            fleet.append(self._create(
                'garage.vehicle', customer_id=partner.id, make_id=makes[make].id,
                model_id=model_record.id, variant_id=variant_record.id,
                category_id=categories[category].id, category=category,
                registration_number=plate, vin=vin,
                fuel_type=fuel, transmission=transmission,
                manufacturing_year=self.today.year - 3 - index,
                registration_year=self.today.year - 3 - index,
                insurance_expiry=self.today + timedelta(days=15 + index * 20),
                pollution_expiry=self.today + timedelta(days=20 + index * 30) if self.code == 'IN' else False,
                service_interval_months=6, service_interval_km=10000,
            ))
        return fleet

    def populate(self):
        service_price, part_price, _ = self.profile['prices']
        category = self._create('garage.service.category', name='Scheduled and corrective maintenance')
        self.service_type = self._create('garage.service.type', name='Workshop service')
        self.bay = self._create('garage.service.bay', name='Demo Service Bay')
        self.hold = self._create('garage.hold.reason', name='Waiting for delivery of material', category='parts')
        self.operations = []
        for name, hours, factor in [
            ('Oil and filter service', 1, 1),
            ('Cooling system service', 1.5, 1.4),
            ('Brake inspection and service', 1.25, 1.25),
        ]:
            product = self._create(
                'product.product', name=name, type='service', list_price=round(service_price * factor, 2),
                garage_service_category_id=category.id,
            )
            operation = self._create(
                'garage.service.operation', name=name, category_id=category.id,
                product_id=product.id, standard_hours=hours,
            )
            self._create('garage.labour.rate', name=name, operation_id=operation.id, rate=product.list_price)
            self.operations.append(operation)
        self.parts = [
            self._create('product.product', name=name, type='consu', garage_part=True,
                         list_price=round(part_price * factor, 2), standard_price=round(part_price * factor * .55, 2))
            for name, factor in [('Oil filter', 1), ('Cooling system consumables', 1.2), ('Brake service kit', 1.5)]
        ]
        self.bank = self.env['account.journal'].search([
            ('company_id', '=', self.company.id), ('type', '=', 'bank'),
            ('inbound_payment_method_line_ids', '!=', False),
        ], limit=1)
        self.payment_method = self.bank.inbound_payment_method_line_ids.filtered(
            lambda method: method.code == 'manual'
        )[:1]
        if not self.payment_method.payment_account_id:
            self.payment_method.payment_account_id = self.bank.default_account_id

        self._seed_visits(self._fleet())

    def _seed_visits(self, fleet):
        current_month = self.today.replace(day=1)
        for month in range(13):
            start = current_month - relativedelta(months=13 - month)
            for slot, day in enumerate((4, 10, 17, 24)):
                outcome = ('paid', 'partial', 'outstanding', 'ready')[slot]
                self._visit(fleet[(month + slot) % len(fleet)], start.replace(day=day), month, slot, outcome)
        for slot, outcome in enumerate(('issued', 'hold', 'no_show', 'booked', 'cancelled')):
            day = self.today + timedelta(days=slot + 1) if outcome == 'booked' else self.today - timedelta(days=slot + 1)
            self._visit(fleet[slot % len(fleet)], day, 13, slot, outcome)

    def _visit(self, vehicle, day, month, slot, outcome):
        local = pytz.timezone(self.profile['timezone'])
        start = local.localize(datetime.combine(day, time(9))).astimezone(pytz.UTC).replace(tzinfo=None)
        operation_index = (month + slot) % len(self.operations)
        operation = self.operations[operation_index]
        part = self.parts[operation_index]
        customer = vehicle.customer_id
        odometer = 25000 + month * 750 + slot * 120
        source_values = {'customer_id': customer.id, 'vehicle_id': vehicle.id}
        appointment = self._create(
            'garage.appointment', **source_values, bay_id=self.bay.id, start=start,
            end=start + timedelta(hours=3), complaint=operation.name, odometer=odometer,
        )
        _stamp(appointment, create_date=start - timedelta(days=1))
        if outcome == 'no_show':
            appointment.write({'state': 'no_show', 'change_reason': 'Synthetic missed booking'})
            return
        if outcome == 'booked':
            return

        lead = self.env['crm.lead']
        if slot in (0, 2):
            lead = self._create(
                'crm.lead', name=f'{operation.name} enquiry', type='opportunity',
                partner_id=customer.id, garage_vehicle_id=vehicle.id,
                garage_service_type_id=self.service_type.id, user_id=self.manager.id,
                expected_revenue=operation.product_id.list_price + part.list_price,
            )
            _stamp(lead, create_date=start - timedelta(days=2))
        appointment.action_arrived()
        job = self._create(
            'garage.job.card', **source_values, appointment_id=appointment.id, lead_id=lead.id,
            date=start, expected_delivery=appointment.end, odometer=odometer, bay_id=self.bay.id,
            service_type_id=self.service_type.id, service_type='periodic',
            technician_ids=[Command.set(self.technician.ids)],
            complaint_ids=[Command.create({'name': operation.name})],
            line_ids=[Command.create({
                'name': operation.name, 'operation_id': operation.id, 'product_id': operation.product_id.id,
                'planned_hours': operation.standard_hours, 'labour_charge': operation.product_id.list_price,
            })],
        )
        _stamp(job, create_date=start)
        appointment.write({'state': 'converted'})
        job.action_generate_inspections()
        _stamp(job.inspection_ids, create_date=start)
        if outcome == 'cancelled':
            job.cancellation_reason = 'Synthetic cancellation before work approval'
            job.action_cancel()
            _stamp(job, cancelled_at=start + timedelta(minutes=15))
            return

        self._sign(job, 'reception', self.manager, start + timedelta(minutes=10))
        job.action_start_diagnosis()
        order = self.env['sale.order'].browse(job.action_create_estimate()['res_id'])
        order.write({'date_order': start, 'order_line': [Command.create({
            'product_id': part.id, 'product_uom_qty': 2, 'price_unit': part.list_price,
        })]})
        order.action_garage_issue()
        if outcome == 'issued':
            return
        order.write({
            'garage_approver_id': customer.id, 'garage_consent_channel': 'in_person',
            'garage_consent_evidence': 'Synthetic work authorization for this demonstration.',
        })
        order.action_garage_approve()
        approval = start + timedelta(minutes=25)
        _stamp(order, date_order=start, garage_recorded_at=approval, create_date=start,
               validity_date=day + timedelta(days=self.company.garage_estimate_validity_days))
        self._prepare_authorized_job(job, order, start, month, outcome)
        self._sign(job, 'technical', self.technician, start + timedelta(minutes=30))
        job.action_progress()
        if outcome == 'hold':
            job.write({
                'hold_reason_id': self.hold.id, 'hold_reason': 'Replacement part backordered',
                'hold_responsible_id': self.manager.id,
            })
            job.action_hold()
            return

        work_start = start + timedelta(minutes=35)
        work_end = work_start + timedelta(hours=operation.standard_hours, minutes=5 * (month % 4))
        for kind, count, actor, stamp in [
            ('issue', 2, self.manager, work_start),
            ('consume', 1, self.technician, work_end),
            ('return', 1, self.manager, work_end),
        ]:
            movement = self.env['garage.part.movement'].with_user(actor).sudo().create({
                'job_id': job.id, 'product_id': part.id, 'kind': kind, 'quantity': count,
                'reason': 'Synthetic workshop material movement',
            })
            _stamp(movement, recorded_at=stamp, create_date=stamp)
        self._record_labour(job, work_start, work_end)
        job.work_complete = True
        job.action_progress()
        self._sign(job, 'final', self.inspector, work_end + timedelta(minutes=5))
        job.action_progress()

        invoice = self.env['account.move'].browse(job.action_create_invoice()['res_id'])
        invoice.write({'invoice_date': day, 'date': day})
        invoice.action_post()
        if outcome == 'ready':
            return
        if outcome in ('paid', 'partial'):
            amount = invoice.amount_total if outcome == 'paid' else invoice.currency_id.round(invoice.amount_total / 2)
            self.env['account.payment.register'].with_context(
                active_model='account.move', active_ids=invoice.ids,
            ).create({
                'amount': amount, 'journal_id': self.bank.id,
                'payment_method_line_id': self.payment_method.id, 'payment_date': day,
            })._create_payments()
        if invoice.amount_residual:
            job.credit_release_reason = 'Synthetic customer account with approved credit terms'
            job.action_credit_release()
            _stamp(job, credit_release_at=work_end + timedelta(minutes=10))

        self._sign(job, 'delivery', self.manager, work_end + timedelta(minutes=15))
        job.write({
            'delivery_recipient': customer.name,
            'delivery_acknowledgment': 'Synthetic vehicle handover recorded.',
        })
        job.action_progress()
        job.action_progress()
        _stamp(job, delivered_at=work_end + timedelta(minutes=20), closed_at=work_end + timedelta(minutes=25))
        reminder = self.env['garage.service.reminder'].search([('job_id', '=', job.id), ('kind', '=', 'service')])
        due = day + relativedelta(months=vehicle.service_interval_months)
        reminder.due_date = due
        if due < self.today and slot == 0:
            reminder.write({'feedback': 'Synthetic service follow-up completed.', 'satisfaction': str(4 + month % 2)})
            reminder.action_followed_up()

    def _prepare_authorized_job(self, job, order, start, month, outcome):
        pass

    def _record_labour(self, job, work_start, work_end):
        self.env['garage.job.time.entry'].with_user(self.technician).sudo().create({
            'job_id': job.id, 'operation_line_id': job.line_ids.id, 'technician_id': self.technician.id,
            'start': work_start, 'end': work_end,
        })

    def _sign(self, job, phase, user, stamp):
        inspections = job.inspection_ids.filtered(lambda item: item.phase == phase).with_user(user).sudo()
        inspections.line_ids.write({'result': 'pass'})
        inspections.action_sign()
        _stamp(inspections, signed_at=stamp)
