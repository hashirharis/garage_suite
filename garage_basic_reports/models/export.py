import base64
from datetime import date, timedelta
from io import BytesIO

import pytz
import xlsxwriter

from odoo import _, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.tools.safe_eval import safe_eval


# Action ID, date field, columns. The existing report action remains the
# authoritative source for the model, report domain and label.
JOB_COLUMNS = 'name date customer_id vehicle_id advisor_id state'
REPORTS = {
    'jobs': ('date', JOB_COLUMNS + ' estimated_hours actual_hours'),
    'inspections': ('create_date', 'job_id template_id phase state signed_by signed_at'),
    'appointments': ('start', 'name start end customer_id vehicle_id bay_id state'),
    'labour': ('job_id.date', 'job_id operation_id name planned_hours labour_charge currency_id'),
    'time': ('start', 'job_id technician_id start end hours'),
    'parts': ('recorded_at', 'job_id recorded_at product_id kind quantity uom_id'),
    'estimates': ('date_order', 'name garage_job_id partner_id date_order garage_version garage_consent amount_total currency_id'),
    'followups': ('due_date', 'name job_id customer_id due_date kind state satisfaction'),
    'revenue': ('invoice_date', 'name invoice_date garage_job_id partner_id move_type amount_total_signed amount_residual_signed company_currency_id'),
    'collections': ('date', 'name date partner_id journal_id payment_type amount currency_id'),
    'customer_history': ('date', JOB_COLUMNS),
    'vehicle_history': ('date', JOB_COLUMNS),
    'margin': ('date', JOB_COLUMNS + ' service_revenue service_cost service_margin currency_id'),
    'labour_revenue': ('date', 'move_id date garage_job_id product_id garage_line_kind garage_revenue company_currency_id'),
    'pending_delivery': ('expected_delivery', JOB_COLUMNS + ' expected_delivery'),
    'service_frequency': ('date', JOB_COLUMNS + ' closed_at'),
    'outstanding': ('invoice_date', 'name invoice_date invoice_date_due garage_job_id partner_id amount_residual currency_id'),
}
FINANCE = {'revenue', 'collections', 'labour_revenue', 'outstanding'}


class GarageReportExport(models.TransientModel):
    _name = 'garage.report.export'
    _description = 'Garage Report Export'

    report_key = fields.Selection(selection='_report_choices', required=True)
    date_from = fields.Date(string='From')
    date_to = fields.Date(string='Through')
    file_data = fields.Binary(readonly=True, attachment=False)
    file_name = fields.Char(readonly=True)

    def _allowed(self, key):
        user = self.env.user
        if not user.has_group('garage_core.group_garage_staff'):
            return False
        if key in FINANCE:
            return any(user.has_group('garage_core.group_garage_' + role) for role in ('cashier', 'owner'))
        if key == 'margin':
            return any(user.has_group('garage_core.group_garage_' + role) for role in ('manager', 'owner'))
        if key == 'estimates':
            return any(user.has_group('garage_core.group_garage_' + role) for role in ('user', 'cashier', 'owner'))
        return True

    def _report_choices(self):
        return [(key, self.env.ref('garage_basic_reports.' + key + '_action').sudo().name)
                for key in REPORTS if self._allowed(key)]

    def _report_data(self, limit):
        self.ensure_one()
        self.check_access('read')
        key = self.report_key
        if key not in REPORTS or not self._allowed(key):
            raise AccessError(_('You do not have access to this Garage report.'))
        if self.date_from and self.date_to and self.date_to < self.date_from:
            raise UserError(_('The end date must be on or after the start date.'))
        action = self.env.ref('garage_basic_reports.' + key + '_action').sudo()
        date_field, column_string = REPORTS[key]
        model = self.env[action.res_model]
        domain = list(safe_eval(action.domain or '[]'))
        field_model = model
        for name in date_field.split('.')[:-1]:
            field_model = self.env[field_model._fields[name].comodel_name]
        is_datetime = field_model._fields[date_field.split('.')[-1]].type == 'datetime'
        zone = pytz.timezone(self.env.context.get('tz') or self.env.user.tz or 'UTC')

        def boundary(day):
            if not is_datetime:
                return day
            local = zone.localize(fields.Datetime.to_datetime(day))
            return local.astimezone(pytz.UTC).replace(tzinfo=None)

        if self.date_from:
            domain.append((date_field, '>=', boundary(self.date_from)))
        if self.date_to:
            domain.append((date_field, '<', boundary(self.date_to + timedelta(days=1))))
        columns = column_string.split()
        labels = model.fields_get(columns, attributes=['string', 'selection', 'type'])
        records = model.search(domain, limit=limit + 1)
        if len(records) > limit:
            raise UserError(_('This export exceeds %s rows. Narrow the date range and try again.', limit))
        rows = []
        for record in records.read(columns):
            row = []
            for name in columns:
                value = record[name]
                metadata = labels[name]
                if metadata['type'] == 'many2one':
                    value = value[1] if value else ''
                elif metadata['type'] == 'selection':
                    value = dict(metadata['selection']).get(value, '')
                elif metadata['type'] == 'datetime' and value:
                    value = fields.Datetime.context_timestamp(self, value).strftime('%Y-%m-%d %H:%M')
                row.append('' if value is False or value is None else value)
            rows.append(row)
        return action.name, [labels[name]['string'] for name in columns], rows

    def action_pdf(self):
        self._report_data(500)
        return self.env.ref('garage_basic_reports.action_export_pdf').report_action(self)

    def action_excel(self):
        title, headers, rows = self._report_data(20000)
        output = BytesIO()
        with xlsxwriter.Workbook(output, {'in_memory': True, 'strings_to_formulas': False,
                                          'strings_to_urls': False}) as workbook:
            sheet = workbook.add_worksheet('Garage report')
            heading = workbook.add_format({'bold': True, 'bg_color': '#153B4C', 'font_color': '#FFFFFF'})
            sheet.write(0, 0, title, heading)
            sheet.write_row(2, 0, headers, heading)
            date_format = workbook.add_format({'num_format': 'yyyy-mm-dd'})
            for row_index, row in enumerate(rows, 3):
                for column_index, cell in enumerate(row):
                    cell_format = date_format if isinstance(cell, date) else None
                    sheet.write(row_index, column_index, cell, cell_format)
            sheet.freeze_panes(3, 0)
            sheet.autofilter(2, 0, max(2, len(rows) + 2), len(headers) - 1)
            sheet.set_column(0, len(headers) - 1, 22)
        self.write({'file_data': base64.b64encode(output.getvalue()), 'file_name': self.report_key + '.xlsx'})
        return {'type': 'ir.actions.act_url', 'target': 'download',
                'url': f'/web/content?model={self._name}&id={self.id}&field=file_data&filename_field=file_name&download=true'}


class GarageReportPdf(models.AbstractModel):
    _name = 'report.garage_basic_reports.export_pdf'
    _description = 'Garage Report PDF'

    def _get_report_values(self, docids, data=None):
        wizard = self.env['garage.report.export'].browse(docids)
        title, headers, rows = wizard._report_data(500)
        return {'docs': wizard, 'title': title, 'headers': headers, 'rows': rows}
