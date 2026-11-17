from datetime import timedelta

from dateutil.relativedelta import relativedelta
from odoo import Command, fields
from odoo.addons.garage_demo_common.seed import WorkshopDemo, _stamp


class ProDemo(WorkshopDemo):

    def _company_name(self, country):
        return 'Garage Pro Demo'

    def _staff(self, name, role, **values):
        group = {
            'manager': 'garage_suite_pro.group_garage_pro_manager',
            'buyer': 'garage_suite_pro.group_garage_buyer',
            'approver': 'garage_suite_pro.group_garage_purchase_approver',
        }.get(role, f'garage_core.group_garage_{role}')
        return self.env['res.users'].create({
            'name': f'Demo {name}',
            'login': 'garage-pro-demo-' + name.lower().replace(' ', '-'),
            'company_id': self.company.id,
            'company_ids': [Command.set(self.company.ids)],
            'group_ids': [Command.link(self.env.ref(group).id)],
            'tz': self.profile['timezone'],
            **values,
        })

    def _fleet_identity(self, index):
        return (
            f'PRO-DEMO-{index + 1:04d}',
            f'GSPIN{index + 1:012d}',
            f'pro-demo-owner-{index + 1}@example.invalid',
        )

    def _seed_visits(self, fleet):
        self.technicians = [
            self.technician,
            self._staff('Brake Specialist', 'technician', garage_hourly_cost=710),
            self._staff('Diagnostic Specialist', 'technician', garage_hourly_cost=860),
        ]
        calendar = self._create(
            'resource.calendar', name='Demo workshop roster', tz=self.profile['timezone'],
            attendance_ids=[Command.create({
                'name': 'Workshop hours', 'dayofweek': str(day), 'hour_from': 8, 'hour_to': 18,
            }) for day in range(7)],
        )
        self.employees = {
            user.id: self._create(
                'hr.employee', name=user.name, user_id=user.id, resource_calendar_id=calendar.id,
            ) for user in self.technicians
        }
        self.insurer = self._create('res.partner', name='Demo Motor Insurance', is_company=True)
        self.contracts = {}
        for index, vehicle in enumerate(fleet[:3]):
            contract = self._create(
                'garage.service.contract', customer_id=vehicle.customer_id.id, vehicle_ids=[Command.link(vehicle.id)],
                kind=('amc', 'fleet', 'warranty')[index],
                date_start=self.today - relativedelta(months=15),
                date_end=self.today + relativedelta(months=index + 1),
                visit_limit=30, coverage_limit=60000, contract_value=24000 + index * 9000,
                terms='Demo maintenance coverage. Declared work remains subject to customer consent.',
            )
            contract.action_activate()
            self.contracts[vehicle.id] = contract

        first = self.today.replace(day=1)
        slots = [
            (first - relativedelta(months=13 - month) + timedelta(days=day - 1), month, slot, outcome)
            for month in range(13)
            for slot, (day, outcome) in enumerate(zip(
                (4, 10, 17, 23),
                (
                    'paid' if month % 4 == 0 else 'outstanding',
                    'partial' if month % 4 == 2 else 'outstanding',
                    'outstanding',
                    'ready',
                ),
            ))
        ]
        used = {item[0] for item in slots}
        recent = [self.today - timedelta(days=n) for n in range(2, 13) if self.today - timedelta(days=n) not in used]
        for slot, (day, outcome) in enumerate(zip(sorted(recent[:7]), ('paid', 'ready', 'partial', 'paid', 'hold', 'issued', 'cancelled'))):
            slots.append((day, 13, slot, outcome))
        slots.append((self.today + timedelta(days=2), 13, 7, 'booked'))
        for index, (day, _, slot, outcome) in enumerate(sorted(slots)):
            self.technician = self.technicians[index % len(self.technicians)]
            self._visit(fleet[index % len(fleet)], day, index, slot, outcome)
        self.technician = self.technicians[0]

        approved = self.env['garage.contract.entitlement'].search([
            ('company_id', '=', self.company.id), ('state', '=', 'approved'), ('job_id.state', '=', 'closed'),
        ])
        approved.action_consume()
        self._seed_inventory_and_purchasing(fleet[0])

    def _prepare_authorized_job(self, job, order, start, month, outcome):
        if month % 5 in (1, 4):
            # Some visits miss their promised time; the actual handover is recorded by the workflow.
            job.expected_delivery = start + timedelta(minutes=65)
        if month % 7 == 1:
            insurer_share = self.company.currency_id.round(order.amount_total * .7)
            claim = self.env['garage.insurance.claim'].create({
                'name': f'DEMO-CLAIM-{month + 1:03d}', 'job_id': job.id, 'estimate_id': order.id,
                'insurer_id': self.insurer.id, 'policy_reference': f'DEMO-POL-{job.vehicle_id.id}',
                'assessment': 'Demo survey completed with documented repair scope.',
                'insurer_share': insurer_share, 'customer_share': order.amount_total - insurer_share,
            })
            claim.action_submit()
            claim.approval_evidence = 'Demo surveyor approved this estimate revision.'
            claim.action_approve()
            _stamp(claim, approved_at=start + timedelta(minutes=28))
        elif (contract := self.contracts.get(job.vehicle_id.id)) and month % 5 != 2:
            item = self.env['garage.contract.entitlement'].create({
                'contract_id': contract.id, 'job_id': job.id, 'amount': 850,
                'scope': 'Scheduled service labour allowance',
            })
            item.action_approve()
            _stamp(item, approved_at=start + timedelta(minutes=28))

        if outcome == 'hold':
            task_model = self.env['garage.workshop.task']
            common = {'job_id': job.id, 'employee_id': self.employees[self.technician.id].id}
            scheduled = task_model.create({
                **common, 'name': 'Inspect replacement component', 'planned_start': start + timedelta(hours=1),
                'planned_end': start + timedelta(hours=2),
            })
            scheduled.action_schedule()
            task_model.create({
                **common, 'name': 'Install replacement component', 'planned_start': start + timedelta(days=7),
                'planned_end': start + timedelta(days=7, hours=1),
                'predecessor_ids': [Command.link(scheduled.id)],
            })

    def _record_labour(self, job, work_start, work_end):
        tasks = self.env['garage.workshop.task']
        common = {'job_id': job.id, 'employee_id': self.employees[self.technician.id].id, 'bay_id': job.bay_id.id}
        prep = tasks.create({
            **common, 'name': 'Prepare bay and parts', 'planned_start': work_start - timedelta(minutes=15),
            'planned_end': work_start,
        })
        prep.action_schedule()
        prep.action_start()
        prep.action_done()
        _stamp(prep, completed_at=work_start)
        operation = tasks.create({
            **common, 'name': job.line_ids.name, 'operation_line_id': job.line_ids.id,
            'planned_start': work_start,
            'planned_end': work_start + timedelta(hours=job.line_ids.planned_hours),
            'predecessor_ids': [Command.link(prep.id)],
        })
        operation.action_schedule()
        operation.action_start()
        common_time = {
            'job_id': job.id, 'operation_line_id': job.line_ids.id, 'technician_id': self.technician.id,
            'start': work_start, 'end': work_end,
        }
        self.env['garage.job.time.entry'].with_user(self.technician).sudo().create({
            **common_time, 'garage_task_id': operation.id,
        })
        operation.action_done()
        _stamp(operation, completed_at=work_end)

    def _seed_inventory_and_purchasing(self, vehicle):
        part = self._create(
            'product.product', name='Demo Air Intake Filter', default_code='PRO-DEMO-AIR',
            type='consu', is_storable=True, garage_part=True, list_price=980, standard_price=560,
            garage_oem_reference='DEMO-OEM-401', garage_part_brand='Workshop Demo',
        )
        self._create(
            'garage.part.fitment', product_tmpl_id=part.product_tmpl_id.id, make_id=vehicle.make_id.id,
            model_id=vehicle.model_id.id, evidence='Synthetic fitment catalogue for demonstrations',
        )
        self.parts[0].product_tmpl_id.garage_alternative_ids = [Command.link(part.product_tmpl_id.id)]
        warehouse = self.env['stock.warehouse'].search([('company_id', '=', self.company.id)], limit=1)
        if not warehouse:
            warehouse = self._create('stock.warehouse', name='Demo Workshop Warehouse', code='PRO')
        opening = self.env['stock.quant'].with_context(inventory_mode=True).create({
            'product_id': part.id, 'location_id': warehouse.lot_stock_id.id, 'inventory_quantity': 24,
        })
        opening.action_apply_inventory()
        vendor = self._create('res.partner', name='Demo Parts Distribution', is_company=True, supplier_rank=1)
        self._create(
            'product.supplierinfo', partner_id=vendor.id, product_tmpl_id=part.product_tmpl_id.id,
            price=540, delay=3,
        )
        buyer = self._staff('Purchasing Coordinator', 'buyer')
        approver = self._staff('Purchasing Lead', 'approver')
        for number, qty in enumerate((8, 14, 20), 1):
            req = self.env['garage.purchase.request'].with_user(buyer).sudo().create({
                'company_id': self.company.id, 'product_id': part.id, 'quantity': qty,
                'needed_by': self.today + timedelta(days=number * 3), 'vendor_id': vendor.id,
                'reason': 'Demo reorder for workshop and counter sales',
            })
            req.action_submit()
            if number > 1:
                req.with_user(approver).sudo().action_approve()
                rfq = self.env['purchase.order'].browse(req.action_create_rfq()['res_id'])
                if number == 3:
                    rfq.with_user(approver).sudo().button_confirm()
                    for receipt in rfq.picking_ids:
                        for move in receipt.move_ids:
                            move.quantity = move.product_uom_qty
                        receipt.move_ids.picked = True
                        receipt.button_validate()

        for quantity, discount in ((2, 0), (4, 5), (6, 10)):
            order = self._create(
                'sale.order', partner_id=vehicle.customer_id.id, warehouse_id=warehouse.id,
                order_line=[Command.create({
                    'product_id': part.id, 'product_uom_qty': quantity, 'price_unit': part.list_price,
                    'discount': discount,
                })],
            )
            order.action_confirm()
            for delivery in order.picking_ids:
                delivery.action_assign()
                delivery.move_ids.picked = True
                delivery.button_validate()
