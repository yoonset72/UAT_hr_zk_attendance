# # -*- coding: utf-8 -*-
# ################################################################################
# #
# #    Cybrosys Technologies Pvt. Ltd.
# #
# #    Copyright (C) 2024-TODAY Cybrosys Technologies(<https://www.cybrosys.com>).
# #    Author: Ammu Raj (odoo@cybrosys.com)
# #
# #    You can modify it under the terms of the GNU AFFERO
# #    GENERAL PUBLIC LICENSE (AGPL v3), Version 3.
# #
# #    This program is distributed in the hope that it will be useful,
# #    but WITHOUT ANY WARRANTY; without even the implied warranty of
# #    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# #    GNU AFFERO GENERAL PUBLIC LICENSE (AGPL v3) for more details.
# #
# #    You should have received a copy of the GNU AFFERO GENERAL PUBLIC LICENSE
# #    (AGPL v3) along with this program.
# #    If not, see <http://www.gnu.org/licenses/>.
# #
# ################################################################################

# import datetime
# import time
# import logging
# import pytz
# import time
# from odoo import api, fields, models, _
# from odoo.exceptions import UserError, ValidationError

# _logger = logging.getLogger(__name__)

# try:
#     from zk import ZK, const
# except ImportError:
#     _logger.error("Please install the 'pyzk' library using 'pip install pyzk'.")


# class BiometricDeviceDetails(models.Model):
#     """Model for configuring and connecting biometric device with Odoo"""
#     _name = 'biometric.device.details'
#     _description = 'Biometric Device Details'

#     name = fields.Char(string='Name', required=True, help='Record Name')
#     device_ip = fields.Char(string='Device IP', required=True, help='IP address of the device')
#     port_number = fields.Integer(string='Port Number', required=True, help='Port Number of the device')
#     address_id = fields.Many2one('res.partner', string='Working Address', help='Working address')
#     company_id = fields.Many2one('res.company', string='Company',
#                                  default=lambda self: self.env.user.company_id.id,
#                                  help='Company linked to the device')

#     def _get_connection_object(self):
#         try:
#             return ZK(self.device_ip, port=self.port_number, timeout=30, password=0, ommit_ping=False)
#         except NameError:
#             raise UserError(_("Pyzk module not found. Please install it with 'pip3 install pyzk'."))

#     def device_connect(self, zk):
#         try:
#             conn = zk.connect()
#             return conn
#         except Exception as e:
#             _logger.error("Connection failed: %s", e)
#             return False

#     def action_test_connection(self):
#         zk = self._get_connection_object()
#         try:
#             conn = zk.connect()
#             conn.disconnect()
#             return {
#                 'type': 'ir.actions.client',
#                 'tag': 'display_notification',
#                 'params': {
#                     'message': 'Successfully Connected',
#                     'type': 'success',
#                     'sticky': False
#                 }
#             }
#         except Exception as error:
#             raise ValidationError(f'{error}')

#     def action_set_timezone(self):
#         for info in self:
#             zk = info._get_connection_object()
#             conn = info.device_connect(zk)
#             if conn:
#                 try:
#                     user_tz = self.env.context.get('tz') or self.env.user.tz or 'UTC'
#                     now_utc = pytz.utc.localize(fields.Datetime.now())
#                     user_time = now_utc.astimezone(pytz.timezone(user_tz))
#                     conn.set_time(user_time)
#                     conn.disconnect()
#                     return {
#                         'type': 'ir.actions.client',
#                         'tag': 'display_notification',
#                         'params': {
#                             'message': 'Successfully Set the Time',
#                             'type': 'success',
#                             'sticky': False
#                         }
#                     }
#                 except Exception as e:
#                     raise UserError(_("Failed to set device time: %s") % str(e))
#             else:
#                 raise UserError(_("Connection failed. Please check the device settings."))

   
#      # Only delete data from Odoo
#     def action_clear_attendance(self):
#         for info in self:
#             self._cr.execute("DELETE FROM zk_machine_attendance")

#     def _get_employee_working_hours(self, employee, punch_date):
#         """Get employee's working hours for a specific date"""
#         if not employee.resource_calendar_id:
#             return []
        
#         calendar = employee.resource_calendar_id
#         weekday = punch_date.weekday()  
        
#         attendance_lines = calendar.attendance_ids.filtered(
#             lambda a: int(a.dayofweek) == weekday
#         ).sorted('hour_from')
        
#         return attendance_lines

#     def _calculate_time_difference_minutes(self, time1, time2):
#         """Calculate difference between two times in minutes"""
#         if time1 > time2:
#             return (time1 - time2) * 60
#         return 0

#     def _process_punch_with_working_hours(self, employee, punch_datetime, device_info):
#         """Process punch based on employee's working hours"""
#         zk_attendance = self.env['zk.machine.attendance']
#         hr_attendance = self.env['hr.attendance']
        
#         punch_date = punch_datetime.date()
#         punch_time = punch_datetime.time()
#         punch_hour = punch_time.hour + punch_time.minute / 60.0 
        
#         working_hours = self._get_employee_working_hours(employee, punch_date)
        
#         if not working_hours:
#             _logger.warning(f"No working hours defined for employee {employee.name}")
#             return '0', 0, 0  
        
#         punch_type = '0'  
#         late_minutes = 0
#         early_checkout_minutes = 0
        
#         existing_attendance = hr_attendance.search([
#             ('employee_id', '=', employee.id),
#             ('check_in', '>=', fields.Datetime.to_string(datetime.datetime.combine(punch_date, datetime.time.min))),
#             ('check_in', '<', fields.Datetime.to_string(datetime.datetime.combine(punch_date + datetime.timedelta(days=1), datetime.time.min)))
#         ], order='check_in desc', limit=1)
        
#         if len(working_hours) >= 2:
#             first_slot_start = working_hours[0].hour_from
#             first_slot_end = working_hours[0].hour_to
#             second_slot_start = working_hours[1].hour_from
#             second_slot_end = working_hours[1].hour_to
            
#             if punch_hour < first_slot_start:
#                 punch_type = '0'
#             elif first_slot_start <= punch_hour <= first_slot_end:
#                 if not existing_attendance or existing_attendance.check_out:
#                     punch_type = '0'  
#                     if punch_hour > first_slot_start:
#                         late_minutes = int(self._calculate_time_difference_minutes(punch_hour, first_slot_start))
#                 else:
#                     punch_type = '1'  # Check-out
#                     if punch_hour < first_slot_end:
#                         early_checkout_minutes = int(self._calculate_time_difference_minutes(first_slot_end, punch_hour))
#             elif first_slot_end < punch_hour < second_slot_start:
#                 if existing_attendance and not existing_attendance.check_out:
#                     punch_type = '1'  # Check-out
#                     if punch_hour < first_slot_end:
#                         early_checkout_minutes = int(self._calculate_time_difference_minutes(first_slot_end, punch_hour))
#                 else:
#                     punch_type = '0'  # Check-in
#             elif second_slot_start <= punch_hour <= second_slot_end:
#                 if existing_attendance and not existing_attendance.check_out:
#                     punch_type = '1'  # Check-out
#                     if punch_hour < second_slot_end:
#                         early_checkout_minutes = int(self._calculate_time_difference_minutes(second_slot_end, punch_hour))
#                 else:
#                     punch_type = '0'  # Check-in
#                     if punch_hour > second_slot_start:
#                         late_minutes = int(self._calculate_time_difference_minutes(punch_hour, second_slot_start))
#             else:
#                 punch_type = '1'  # Check-out
#         else:
#             slot_start = working_hours[0].hour_from
#             slot_end = working_hours[0].hour_to
            
#             if punch_hour <= slot_end:
#                 if not existing_attendance or existing_attendance.check_out:
#                     punch_type = '0'  # Check-in
#                     if punch_hour > slot_start:
#                         late_minutes = int(self._calculate_time_difference_minutes(punch_hour, slot_start))
#                 else:
#                     punch_type = '1'  # Check-out
#                     if punch_hour < slot_end:
#                         early_checkout_minutes = int(self._calculate_time_difference_minutes(slot_end, punch_hour))
#             else:
#                 punch_type = '1'  # Check-out
        
#         return punch_type, late_minutes, early_checkout_minutes


#     def action_download_attendance(self):
#         start_time = time.time()
#         _logger.info("++++++++++++ Downloading Attendance from Device +++++++++++++")

#         zk_attendance = self.env['zk.machine.attendance']
#         hr_attendance = self.env['hr.attendance']

#         today = fields.Date.today()
#         start_date = datetime.date(2025, 8, 1)  # change to dynamic if needed
#         end_date = today

#         for info in self:
#             zk = info._get_connection_object()
#             conn = self.device_connect(zk)
#             if not conn:
#                 raise UserError(_("Unable to connect, please check network/device settings."))

#             try:
#                 self.action_set_timezone()
#                 conn.disable_device()

#                 users = conn.get_users()
#                 all_attendance = conn.get_attendance()
#                 device_tz = pytz.timezone('Asia/Rangoon')

#                 for att in all_attendance:
#                     raw_ts = att.timestamp
#                     local_dt = device_tz.localize(raw_ts) if raw_ts.tzinfo is None else raw_ts.astimezone(device_tz)
#                     att_date = local_dt.date()

#                     if start_date <= att_date <= end_date:
#                         employee = self.env['hr.employee'].search([('employee_number', '=', att.user_id)], limit=1)
#                         if not employee:
#                             user_name = next((u.name for u in users if u.user_id == att.user_id), "Unknown")
#                             _logger.warning(f"Employee not found for user ID {att.user_id} ({user_name}). Skipping attendance record.")
#                             continue

#                         utc_dt = local_dt.astimezone(pytz.utc)
#                         punching_time = fields.Datetime.to_string(utc_dt)

#                         # Skip exact duplicates
#                         if zk_attendance.search([
#                             ('device_id_num', '=', att.user_id),
#                             ('punching_time', '=', punching_time)
#                         ], limit=1):
#                             _logger.info(f"Skipping duplicate punch for {att.user_id} at {punching_time}")
#                             continue

#                         # Calculate late/early minutes (still use working hours)
#                         _, late_minutes, early_checkout_minutes = self._process_punch_with_working_hours(
#                             employee, local_dt, info
#                         )

#                         # Determine punch type ourselves
#                         open_attendance = hr_attendance.search([
#                             ('employee_id', '=', employee.id),
#                             ('check_out', '=', False),
#                         ], order="check_in desc", limit=1)

#                         if not open_attendance:
#                             # If first punch of the day and it's afternoon, treat as checkout
#                             punch_type = '1' if local_dt.hour >= 12 else '0'
#                         else:
#                             # If there's an open check-in, this is a checkout
#                             punch_type = '1'

#                         zk_attendance.create({
#                             'employee_id': employee.id,
#                             'device_id_num': att.user_id,
#                             'attendance_type': '1',  # fixed, ignoring device status
#                             'punch_type': punch_type,
#                             'punching_time': punching_time,
#                             'address_id': info.address_id.id,
#                             'late_minutes': late_minutes,
#                             'early_checkout_minutes': early_checkout_minutes,
#                         })
#                         _logger.info(f"Saved punch for {employee.name}: {punching_time} ({'Check-in' if punch_type == '0' else 'Check-out'})")

#                         # Update hr.attendance
#                         if punch_type == '0':  # Check-in
#                             hr_attendance.create({
#                                 'employee_id': employee.id,
#                                 'check_in': punching_time
#                             })
#                         elif punch_type == '1':  # Check-out
#                             if open_attendance:
#                                 open_attendance.write({'check_out': punching_time})
#                             else:
#                                 _logger.warning(f"Check-out without check-in for {employee.name} at {punching_time}")

#             finally:
#                 conn.enable_device()
#                 conn.disconnect()

#         total_time = time.time() - start_time
#         _logger.info(f"✅ Attendance download completed in {total_time:.2f} seconds.")

#         return {
#             'type': 'ir.actions.act_window',
#             'name': 'Attendance Overview',
#             'res_model': 'zk.machine.attendance',
#             'view_mode': 'tree,form',
#             'domain': [
#                 ('punching_time', '>=', fields.Date.to_string(start_date)),
#                 ('punching_time', '<=', fields.Date.to_string(end_date)),
#             ],
#             'context': {'search_default_group_by_employee_id': 1}
#         }


#     def action_restart_device(self):
#         zk = self._get_connection_object()
#         conn = self.device_connect(zk)
#         if conn:
#             try:
#                 conn.restart()
#             except Exception as e:
#                 raise UserError(_("Failed to restart the device: %s") % str(e))
#             finally:
#                 conn.disconnect()
#         else:
#             raise UserError(_("Unable to connect to device for restart."))


# -*- coding: utf-8 -*-
################################################################################
#
#    Cybrosys Technologies Pvt. Ltd.
#
#    Copyright (C) 2024-TODAY Cybrosys Technologies(<https://www.cybrosys.com>).
#    Author: Ammu Raj (odoo@cybrosys.com)
#
#    You can modify it under the terms of the GNU AFFERO
#    GENERAL PUBLIC LICENSE (AGPL v3), Version 3.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU AFFERO GENERAL PUBLIC LICENSE (AGPL v3) for more details.
#
#    You should have received a copy of the GNU AFFERO GENERAL PUBLIC LICENSE
#    (AGPL v3) along with this program.
#    If not, see <http://www.gnu.org/licenses/>.
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
    """Model for configuring and connecting biometric device with Odoo"""
    _name = 'biometric.device.details'
    _description = 'Biometric Device Details'

    name = fields.Char(string='Name', required=True, help='Record Name')
    device_ip = fields.Char(string='Device IP', required=True, help='IP address of the device')
    port_number = fields.Integer(string='Port Number', required=True, help='Port Number of the device')
    address_id = fields.Many2one('res.partner', string='Working Address', help='Working address')
    company_id = fields.Many2one('res.company', string='Company',
                                 default=lambda self: self.env.user.company_id.id,
                                 help='Company linked to the device')

    def _get_connection_object(self):
        try:
            return ZK(self.device_ip, port=self.port_number, timeout=30, password=0, ommit_ping=False)
        except NameError:
            raise UserError(_("Pyzk module not found. Please install it with 'pip3 install pyzk'."))

    def device_connect(self, zk):
        try:
            conn = zk.connect()
            return conn
        except Exception as e:
            _logger.error("Connection failed: %s", e)
            return False

    def action_test_connection(self):
        zk = self._get_connection_object()
        try:
            conn = zk.connect()
            conn.disconnect()
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'message': 'Successfully Connected',
                    'type': 'success',
                    'sticky': False
                }
            }
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

    # Only delete data from Odoo
    def action_clear_attendance(self):
        for info in self:
            self._cr.execute("DELETE FROM zk_machine_attendance")

    def _get_employee_working_hours(self, employee, punch_date):
        """Get employee's working hours (attendance lines) for a specific date (weekday)."""
        if not employee.resource_calendar_id:
            return []

        calendar = employee.resource_calendar_id
        weekday = punch_date.weekday()

        attendance_lines = calendar.attendance_ids.filtered(
            lambda a: int(a.dayofweek) == weekday
        ).sorted('hour_from')

        return attendance_lines

    def _float_hour_to_time(self, float_hour):
        """Convert float hour (e.g. 8.75) to datetime.time (08:45)."""
        if float_hour is None:
            return None
        hours = int(float_hour)
        minutes = int(round((float_hour - hours) * 60))
        # normalize minute overflow
        if minutes >= 60:
            hours += 1
            minutes -= 60
        hours = max(0, min(23, hours))
        minutes = max(0, min(59, minutes))
        return datetime.time(hours, minutes)

    def _calculate_time_difference_minutes(self, time1, time2):
        """Calculate difference between two numeric hour values (or floats representing hours) in minutes.
           But here we also use it with decimal hours (punch_hour) so keep previous behavior for compatibility."""
        if time1 > time2:
            return (time1 - time2) * 60
        return 0

    def _process_punch_with_working_hours(self, employee, punch_datetime, device_info):
        """Return late and early checkout minutes using employee working hours (keeps previous interface)."""
        punch_date = punch_datetime.date()
        punch_time = punch_datetime.time()
        punch_hour = punch_time.hour + punch_time.minute / 60.0

        working_hours = self._get_employee_working_hours(employee, punch_date)
        if not working_hours:
            return '0', 0, 0

        if len(working_hours) >= 2:
            first_slot_start = working_hours[0].hour_from
            first_slot_end = working_hours[0].hour_to
            second_slot_start = working_hours[1].hour_from
            second_slot_end = working_hours[1].hour_to
        else:
            first_slot_start = working_hours[0].hour_from
            first_slot_end = working_hours[0].hour_to
            second_slot_start = None
            second_slot_end = None

        late_minutes = 0
        early_checkout_minutes = 0

        # Normal late calculation
        if punch_hour > first_slot_start and punch_hour <= first_slot_end:
            late_minutes = int(self._calculate_time_difference_minutes(punch_hour, first_slot_start))

        # If employee missed entire morning slot but came in afternoon
        elif second_slot_start and punch_hour >= second_slot_start:
            # Treat as if they were late from morning slot start
            late_minutes = int(self._calculate_time_difference_minutes(punch_hour, first_slot_start))

        # Early checkout calculation
        if second_slot_end is not None:
            if punch_hour < second_slot_end:
                early_checkout_minutes = int(self._calculate_time_difference_minutes(second_slot_end, punch_hour))

        return '0', late_minutes, early_checkout_minutes


    def action_download_attendance(self):
        """
        Download raw punches, store them in zk.machine.attendance (raw),
        then group punches per employee/day and create/update hr.attendance.
        Creates a record even if only check-in or only check-out exists.
        Leaves previous day's check_out blank if missing (does not auto-close with next day's punch).
        """
        import pytz
        import datetime
        import time

        start_time = time.time()
        _logger.info("++++++++++++ Downloading Attendance from Device +++++++++++++")

        zk_attendance = self.env['zk.machine.attendance']
        hr_attendance = self.env['hr.attendance']

        today = fields.Date.today()
        start_date = datetime.date(2025, 8, 1)
        end_date = today

        def make_naive_utc(dt):
            """Convert datetime with or without tzinfo to naive UTC datetime."""
            if dt is None:
                return False
            if dt.tzinfo:
                dt = dt.astimezone(pytz.utc)
                return dt.replace(tzinfo=None)
            return dt

        for info in self:
            zk = info._get_connection_object()
            conn = self.device_connect(zk)
            if not conn:
                raise UserError(_("Unable to connect, please check network/device settings."))

            try:
                self.action_set_timezone()
                conn.disable_device()

                users = conn.get_users()
                all_attendance = conn.get_attendance()
                device_tz = pytz.timezone('Asia/Rangoon')

                grouped_punches = {}  # {(employee.id, date): [datetime, ...]}

                for att in all_attendance:
                    raw_ts = att.timestamp
                    local_dt = device_tz.localize(raw_ts) if raw_ts.tzinfo is None else raw_ts.astimezone(device_tz)
                    att_date = local_dt.date()

                    if not (start_date <= att_date <= end_date):
                        continue

                    employee = self.env['hr.employee'].search([('employee_number', '=', att.user_id)], limit=1)
                    if not employee:
                        user_name = next((u.name for u in users if u.user_id == att.user_id), "Unknown")
                        _logger.warning(f"Employee not found for user ID {att.user_id} ({user_name}). Skipping.")
                        continue

                    # store raw punch in zk.machine.attendance
                    utc_dt = local_dt.astimezone(pytz.utc)
                    punching_time = fields.Datetime.to_string(utc_dt)

                    if not zk_attendance.search([
                        ('device_id_num', '=', att.user_id),
                        ('punching_time', '=', punching_time)
                    ], limit=1):
                        zk_attendance.create({
                            'employee_id': employee.id,
                            'device_id_num': att.user_id,
                            'attendance_type': str(getattr(att, 'status', '1')),
                            'punch_type': str(getattr(att, 'punch', '0')),
                            'punching_time': punching_time,
                            'address_id': info.address_id.id,
                        })
                        _logger.info(f"Saved raw punch for {employee.name} at {punching_time}")

                    key = (employee.id, att_date)
                    grouped_punches.setdefault(key, []).append(local_dt)

                def localize_if_naive(dt, tz):
                    return tz.localize(dt) if dt.tzinfo is None else dt.astimezone(tz)

                for (emp_id, work_date), punch_list in grouped_punches.items():
                    punch_list = sorted(punch_list)
                    employee = self.env['hr.employee'].browse(emp_id)

                    attendance_lines = self._get_employee_working_hours(employee, work_date)
                    if len(attendance_lines) >= 2:
                        slot1_start = self._float_hour_to_time(attendance_lines[0].hour_from)
                        slot1_end = self._float_hour_to_time(attendance_lines[0].hour_to)
                        slot2_start = self._float_hour_to_time(attendance_lines[1].hour_from)
                        slot2_end = self._float_hour_to_time(attendance_lines[1].hour_to)
                    elif len(attendance_lines) == 1:
                        slot1_start = self._float_hour_to_time(attendance_lines[0].hour_from)
                        slot1_end = self._float_hour_to_time(attendance_lines[0].hour_to)
                        slot2_start = None
                        slot2_end = None
                    else:
                        slot1_start = datetime.time(8, 45)
                        slot1_end = datetime.time(12, 0)
                        slot2_start = datetime.time(13, 0)
                        slot2_end = datetime.time(16, 45)

                    check_in_dt = None
                    check_out_dt = None

                    if len(punch_list) == 1:
                        single_time = punch_list[0].time()
                        if slot2_end and single_time >= slot2_end:
                            check_out_dt = punch_list[0]
                        else:
                            check_in_dt = punch_list[0]
                    else:
                        for p_dt in punch_list:
                            t = p_dt.time()
                            if slot1_start and t < slot1_start:
                                if not check_in_dt or p_dt < check_in_dt:
                                    check_in_dt = p_dt
                            elif slot1_start and t < (slot1_end or datetime.time(23, 59)):
                                if not check_in_dt or p_dt < check_in_dt:
                                    check_in_dt = p_dt
                            elif slot1_end and slot2_end and t < slot2_end:
                                if check_in_dt and (not check_out_dt or p_dt > check_out_dt):
                                    check_out_dt = p_dt
                                elif not check_in_dt:
                                    check_in_dt = p_dt
                            else:
                                if not check_out_dt or p_dt > check_out_dt:
                                    check_out_dt = p_dt

                    vals = {}
                    asia_rangoon_tz = pytz.timezone('Asia/Rangoon')

                    if check_in_dt:
                        localized_in = localize_if_naive(check_in_dt, asia_rangoon_tz)
                        naive_in = make_naive_utc(localized_in.astimezone(pytz.utc))
                        vals['check_in'] = naive_in and naive_in.strftime('%Y-%m-%d %H:%M:%S')
                    else:
                        # Allow blank check_in for forgotten check-in
                        vals['check_in'] = None

                    if check_out_dt:
                        localized_out = localize_if_naive(check_out_dt, asia_rangoon_tz)
                        naive_out = make_naive_utc(localized_out.astimezone(pytz.utc))
                        if naive_out:
                            if vals.get('check_in'):
                                check_in_date = vals['check_in'][:10]
                                check_out_date = naive_out.strftime('%Y-%m-%d')
                                if check_in_date == check_out_date:
                                    vals['check_out'] = naive_out.strftime('%Y-%m-%d %H:%M:%S')
                                else:
                                    vals['check_out'] = None
                            else:
                                # No check-in but valid check-out — keep it
                                vals['check_out'] = naive_out.strftime('%Y-%m-%d %H:%M:%S')
                        else:
                            vals['check_out'] = None
                    else:
                        vals['check_out'] = None


                    # Check for previous open attendance, but do NOT auto-close it
                    open_attendance = hr_attendance.search([
                        ('employee_id', '=', emp_id),
                        ('check_out', '=', False)
                    ], limit=1)

                    # Safely handle missing check_in
                    if open_attendance:
                        if open_attendance.check_in and open_attendance.check_in.date() < work_date:
                            _logger.warning(
                                f"Previous attendance for {employee.name} on {open_attendance.check_in.date()} "
                                f"has no check-out. Leaving it blank."
                            )
                        elif not open_attendance.check_in:
                            _logger.warning(
                                f"Previous attendance for {employee.name} has no check-in and no check-out. Leaving it blank."
                            )

                    # Create or update today's attendance
                    attendance = hr_attendance.search([
                        ('employee_id', '=', emp_id),
                        ('check_in', '>=', fields.Datetime.to_string(datetime.datetime.combine(work_date, datetime.time.min))),
                        ('check_in', '<', fields.Datetime.to_string(datetime.datetime.combine(work_date, datetime.time.max))),
                    ], limit=1)

                    check_in_val = vals.get('check_in')
                    check_out_val = vals.get('check_out')

                    if attendance:
                        write_vals = {
                            'check_in': check_in_val,
                            'check_out': check_out_val,
                        }
                        attendance.write(write_vals)
                        _logger.info(f"Updated hr.attendance for {employee.name} on {work_date}: {write_vals}")
                    else:
                        if check_in_val or check_out_val:
                            create_vals = {
                                'employee_id': emp_id,
                                'check_in': check_in_val,
                                'check_out': check_out_val,
                            }
                            hr_attendance.create(create_vals)
                            _logger.info(f"Created hr.attendance for {employee.name} on {work_date}: {create_vals}")
                        else:
                            _logger.warning(f"Skipping attendance creation for {employee.name} on {work_date} because both check_in and check_out are missing.")

                    if not check_in_dt or not check_out_dt:
                        _logger.warning(
                            f"Incomplete attendance for {employee.name} on {work_date} - "
                            f"check_in: {check_in_dt}, check_out: {check_out_dt}"
                        )

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
        _logger.info(f"✅ Attendance download & processing completed in {total_time:.2f} seconds.")

        return {
            'type': 'ir.actions.act_window',
            'name': 'Attendance Overview',
            'res_model': 'zk.machine.attendance',
            'view_mode': 'tree,form',
            'domain': [
                ('punching_time', '>=', fields.Date.to_string(start_date)),
                ('punching_time', '<=', fields.Date.to_string(end_date)),
            ],
            'context': {'search_default_group_by_employee_id': 1}
    }




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