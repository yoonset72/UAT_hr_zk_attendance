# -*- coding: utf-8 -*-
################################################################################
#
#    Biometric Device Integration for Odoo
#    Extended to support multiple calendars and night shifts
#
################################################################################

import datetime
import time
import logging
import pytz
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

try:
    from zk import ZK, const
except ImportError:
    _logger.error("Please install the 'pyzk' library using 'pip install pyzk'.")


class BiometricDeviceDetails(models.Model):
    _name = 'biometric.device.details'
    _description = 'Biometric Device Details'

    name = fields.Char(string='Name', required=True)
    device_ip = fields.Char(string='Device IP', required=True)
    port_number = fields.Integer(string='Port Number', required=True)
    address_id = fields.Many2one('res.partner', string='Working Address')
    company_id = fields.Many2one('res.company', default=lambda self: self.env.user.company_id.id)

    def _get_connection_object(self):
        try:
            return ZK(self.device_ip, port=self.port_number, timeout=30, password=0, ommit_ping=False)
        except NameError:
            raise UserError(_("Pyzk module not found. Please install it with 'pip3 install pyzk'."))

    def device_connect(self, zk):
        try:
            return zk.connect()
        except Exception as e:
            _logger.error("Connection failed: %s", e)
            return False

    def action_test_connection(self):
        zk = self._get_connection_object()
        try:
            conn = zk.connect()
            conn.disconnect()
            return {'type': 'ir.actions.client', 'tag': 'display_notification',
                    'params': {'message': 'Successfully Connected', 'type': 'success', 'sticky': False}}
        except Exception as error:
            raise ValidationError(f'{error}')
    
    def action_set_timezone(self):
        for info in self:
            zk = info._get_connection_object()
            conn = info.device_connect(zk)
            if conn:
                try:
                    user_tz = self.env.context.get('tz') or self.env.user.tz or 'UTC'
                    now_utc = pytz.utc.localize(fields.Datetime.now())
                    user_time = now_utc.astimezone(pytz.timezone(user_tz))
                    conn.set_time(user_time)
                    conn.disconnect()
                    return {
                        'type': 'ir.actions.client',
                        'tag': 'display_notification',
                        'params': {
                            'message': 'Successfully Set the Time',
                            'type': 'success',
                            'sticky': False
                        }
                    }
                except Exception as e:
                    raise UserError(_("Failed to set device time: %s") % str(e))
            else:
                raise UserError(_("Connection failed. Please check the device settings."))
    
    def action_clear_attendance(self):
        for info in self:
            self._cr.execute("DELETE FROM zk_machine_attendance")

    def _float_hour_to_time(self, float_hour):
        if float_hour is None:
            return None
        hours = int(float_hour)
        minutes = int(round((float_hour - hours) * 60))
        if minutes >= 60:
            hours += 1
            minutes -= 60
        return datetime.time(hours % 24, minutes)

    def _get_employee_working_hours(self, employee, punch_date):
        calendars = employee.resource_calendar_ids
        if not calendars:
            return []
        weekday = punch_date.weekday()
        lines = self.env['resource.calendar.attendance']
        if isinstance(calendars, models.Model):
            calendars = [calendars]
        for cal in calendars:
            lines |= cal.attendance_ids.filtered(lambda a: int(a.dayofweek) == weekday)
        return lines.sorted('hour_from')

    def _select_shift_type(self, employee, punch_datetime):
        """Return shift type (day/night) and ordered slots for the punch date."""
        punch_date = punch_datetime.date()
        working_hours = self._get_employee_working_hours(employee, punch_date)
        if not working_hours:
            # default night shift if no calendar
            return 'night', [(datetime.time(16, 45), datetime.time(8, 45))]
        # detect night or day shift from slot ordering
        slots = [(self._float_hour_to_time(s.hour_from), self._float_hour_to_time(s.hour_to)) for s in working_hours]
        if slots[0][1] < slots[0][0]:
            return 'night', slots
        else:
            return 'day', slots

    def action_download_attendance(self):
        start_time = time.time()
        _logger.info("Downloading attendance...")

        zk_attendance = self.env['zk.machine.attendance']
        hr_attendance = self.env['hr.attendance']

        today = fields.Date.today()
        start_date = datetime.date(2025, 8, 1)
        end_date = today
        device_tz = pytz.timezone('Asia/Rangoon')

        for info in self:
            zk = self._get_connection_object()
            conn = self.device_connect(zk)
            if not conn:
                raise UserError(_("Unable to connect to device"))

            try:
                conn.disable_device()
                all_attendance = conn.get_attendance()
                grouped_punches = {}

                for att in all_attendance:
                    raw_ts = att.timestamp
                    local_dt = device_tz.localize(raw_ts) if raw_ts.tzinfo is None else raw_ts.astimezone(device_tz)
                    att_date = local_dt.date()
                    if not (start_date <= att_date <= end_date):
                        continue
                    employee = self.env['hr.employee'].search([('employee_number', '=', att.user_id)], limit=1)
                    if not employee:
                        continue
                    utc_dt = local_dt.astimezone(pytz.utc)
                    punching_time = fields.Datetime.to_string(utc_dt)
                    if not zk_attendance.search([('device_id_num', '=', att.user_id), ('punching_time', '=', punching_time)], limit=1):
                        zk_attendance.create({'employee_id': employee.id, 'device_id_num': att.user_id,
                                              'attendance_type': str(getattr(att, 'status', '1')),
                                              'punch_type': str(getattr(att, 'punch', '0')),
                                              'punching_time': punching_time,
                                              'address_id': info.address_id.id})
                    grouped_punches.setdefault(employee.id, []).append(local_dt)

                # Process punches
                for emp_id, punches in grouped_punches.items():
                    punches = sorted(punches)
                    employee = self.env['hr.employee'].browse(emp_id)
                    for punch in punches:
                        if punch.tzinfo is None:
                            punch = device_tz.localize(punch)
                        shift_type, slots = self._select_shift_type(employee, punch)
                        record_created = False

                        if shift_type == 'day':
                            # first slot
                            first_start, first_end = slots[0]
                            second_start, second_end = slots[1] if len(slots) > 1 else (None, None)

                            if punch.time() <= first_end:
                                # check-in for first slot
                                record_id = hr_attendance.create({'employee_id': emp_id,
                                                                 'check_in': fields.Datetime.to_string(punch.astimezone(pytz.utc))}).id
                                record_created = True
                            elif second_start and first_end < punch.time() <= second_end:
                                # check-in if no open attendance else check-out
                                prev_att = hr_attendance.search([('employee_id', '=', emp_id),
                                                                 ('check_out', '=', False),
                                                                 ('check_in', '!=', False),
                                                                 ('check_in', '>=', fields.Datetime.to_string(datetime.datetime.combine(punch.date(), datetime.time(0,0))))],
                                                                order="check_in desc", limit=1)
                                if prev_att:
                                    prev_att.write({'check_out': fields.Datetime.to_string(punch.astimezone(pytz.utc))})
                                else:
                                    record_id = hr_attendance.create({'employee_id': emp_id,
                                                                     'check_in': fields.Datetime.to_string(punch.astimezone(pytz.utc))}).id
                                    record_created = True
                            elif second_end and punch.time() > second_end:
                                prev_att = hr_attendance.search([('employee_id', '=', emp_id),
                                                                 ('check_out', '=', False)],
                                                                order="check_in desc", limit=1)
                                if prev_att:
                                    prev_att.write({'check_out': fields.Datetime.to_string(punch.astimezone(pytz.utc))})
                                else:
                                    # create open attendance with blank check-in
                                    record_id = hr_attendance.create({'employee_id': emp_id,
                                                                     'check_in': False,
                                                                     'check_out': fields.Datetime.to_string(punch.astimezone(pytz.utc))}).id
                                    record_created = True

                        else:  # night shift
                            first_start, first_end = slots[0]
                            if punch.time() <= first_end:
                                record_id = hr_attendance.create({'employee_id': emp_id,
                                                                 'check_in': fields.Datetime.to_string(punch.astimezone(pytz.utc))}).id
                                record_created = True
                            else:
                                prev_att = hr_attendance.search([('employee_id', '=', emp_id),
                                                                 ('check_out', '=', False)],
                                                                order="check_in desc", limit=1)
                                if prev_att:
                                    prev_att.write({'check_out': fields.Datetime.to_string(punch.astimezone(pytz.utc))})
                                else:
                                    # create open attendance with blank check-in
                                    record_id = hr_attendance.create({'employee_id': emp_id,
                                                                     'check_in': False,
                                                                     'check_out': fields.Datetime.to_string(punch.astimezone(pytz.utc))}).id
                                    record_created = True

            finally:
                try:
                    conn.enable_device()
                except Exception:
                    pass
                try:
                    conn.disconnect()
                except Exception:
                    pass

        total_time = time.time() - start_time
        _logger.info(f"Attendance download completed in {total_time:.2f} seconds.")
        return {'type': 'ir.actions.act_window', 'name': 'Attendance Overview',
                'res_model': 'zk.machine.attendance', 'view_mode': 'tree,form',
                'domain': [('punching_time', '>=', fields.Date.to_string(start_date)),
                           ('punching_time', '<=', fields.Date.to_string(end_date))],
                'context': {'search_default_group_by_employee_id': 1}}


    # ---------------- Device Restart ---------------- #

    def action_restart_device(self):
        zk = self._get_connection_object()
        conn = self.device_connect(zk)
        if conn:
            try:
                conn.restart()
            except Exception as e:
                raise UserError(_("Failed to restart the device: %s") % str(e))
            finally:
                conn.disconnect()
        else:
            raise UserError(_("Unable to connect to device for restart."))
