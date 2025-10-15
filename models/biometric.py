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

    # ---------------- Utility ---------------- #

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


    # ---------------- Actions ---------------- #

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
    
    # ------------------------------------------------------------------------

    def _handle_same_day_hour_duplicate(self, hr_attendance, emp_id, punch, is_check_in=True):
        """
        Handle duplicates within a 60-minute window for check_in or check_out.
        - For check-in: take earliest punch.
        - For check-out: take latest punch.
        """
        punch_utc = punch.astimezone(pytz.utc)
        punch_str = fields.Datetime.to_string(punch_utc)

        # Define a 60-minute window
        window_start = punch_utc - datetime.timedelta(minutes=60)
        window_end = punch_utc + datetime.timedelta(minutes=60)

        if is_check_in:
            # Search for earliest check-in in the window
            records = hr_attendance.search([
                ('employee_id', '=', emp_id),
                ('check_in', '>=', fields.Datetime.to_string(window_start)),
                ('check_in', '<=', fields.Datetime.to_string(window_end))
            ])
            closest_record = None
            earliest_dt = None

            for rec in records:
                if not rec.check_in:
                    continue
                existing_dt = fields.Datetime.from_string(rec.check_in)
                if existing_dt.tzinfo is None:
                    existing_dt = pytz.utc.localize(existing_dt)

                if earliest_dt is None or existing_dt > punch_utc:
                    earliest_dt = existing_dt
                    closest_record = rec

            if closest_record:
                if punch_utc < earliest_dt:
                    closest_record.write({'check_in': punch_str})
                    return 'updated'
                else:
                    return 'discard'
            else:
                return 'new'

        else:  # check-out
            # Search for latest check-out in the window
            records = hr_attendance.search([
                ('employee_id', '=', emp_id),
                ('check_out', '>=', fields.Datetime.to_string(window_start)),
                ('check_out', '<=', fields.Datetime.to_string(window_end))
            ])
            closest_record = None
            latest_dt = None

            for rec in records:
                if not rec.check_out:
                    continue
                existing_dt = fields.Datetime.from_string(rec.check_out)
                if existing_dt.tzinfo is None:
                    existing_dt = pytz.utc.localize(existing_dt)

                if latest_dt is None or existing_dt < punch_utc:
                    latest_dt = existing_dt
                    closest_record = rec

            if closest_record:
                if punch_utc > latest_dt:
                    closest_record.write({'check_out': punch_str})
                    return 'updated'
                else:
                    return 'discard'
            else:
                return 'new'


    # --------------------------------------------------------------------------

    def _select_shift_type(self, employee, punch_datetime, is_check_in=None):
        """
        Determine shift type (day/night) based on punch time and attendance logic.
        Duplicate handling is done first to avoid misclassification.
        If is_check_in is None, it will be inferred based on attendance state.
        """

        hr_attendance = self.env['hr.attendance']

        # ---- Step 1: Check duplicates for both in and out ----
        duplicate_checkin = self._handle_same_day_hour_duplicate(
            hr_attendance=hr_attendance,
            emp_id=employee.id,
            punch=punch_datetime,
            is_check_in=True
        )
        duplicate_checkout = self._handle_same_day_hour_duplicate(
            hr_attendance=hr_attendance,
            emp_id=employee.id,
            punch=punch_datetime,
            is_check_in=False
        )

        if duplicate_checkin in ('discard', 'updated') or duplicate_checkout in ('discard', 'updated'):
            _logger.debug(
                "[DUPLICATE] Emp: %s Punch: %s handled as duplicate (%s/%s). Skipping shift detection.",
                employee.id, punch_datetime, duplicate_checkin, duplicate_checkout
            )
            return None, None

        # ---- Step 2: Infer check-in/check-out if not provided ----
        if is_check_in is None:
            punch_date = punch_datetime.date()
            open_attendance = hr_attendance.search([
                ('employee_id', '=', employee.id),
                ('check_out', '=', False),
                ('check_in', '<=', fields.Datetime.to_string(datetime.datetime.combine(punch_date, datetime.time.max)))
            ], limit=1)
            is_check_in = False if open_attendance else True

        # ---- Step 3: Get working hours and slots ----
        punch_date = punch_datetime.date()
        punch_time = punch_datetime.time()
        working_hours = self._get_employee_working_hours(employee, punch_date)

        slots = (
            [(datetime.time(8, 45), datetime.time(16, 45))]
            if not working_hours
            else [
                (self._float_hour_to_time(s.hour_from), self._float_hour_to_time(s.hour_to))
                for s in working_hours
            ]
        )

        # ---- Step 4: Shift determination ----
        if len(employee.resource_calendar_ids) == 1:
            # Single-shift employee
            shift_type = 'night' if slots[0][0] == datetime.time(0, 0) else 'day'
            _logger.debug(
                "[SHIFT] Emp: %s Punch: %s Single shift_type: %s",
                employee.id, punch_datetime, shift_type
            )
            return shift_type, slots
        else:
            # Multi-shift employee
            day_shift_slots = []
            for i, (start, end) in enumerate(slots):
                if end.hour == 12 and i + 1 < len(slots):
                    next_start, next_end = slots[i + 1]
                    if next_start.hour == 13:
                        day_shift_slots = [(start, end), (next_start, next_end)]
                        break

            relevant_slots = day_shift_slots if day_shift_slots else slots

            attendances_today = hr_attendance.search([
                ('employee_id', '=', employee.id),
                ('check_in', '>=', datetime.datetime.combine(punch_date, datetime.time.min)),
                ('check_in', '<=', datetime.datetime.combine(punch_date, datetime.time.max)),
                ('check_out', '=', False)
            ], order='check_in')

            prev_date = punch_date - datetime.timedelta(days=1)
            attendances_prev = hr_attendance.search([
                ('employee_id', '=', employee.id),
                ('check_in', '>=', datetime.datetime.combine(prev_date, datetime.time.min)),
                ('check_in', '<=', datetime.datetime.combine(prev_date, datetime.time.max)),
                ('check_out', '=', False)
            ], order='check_in')

            # Decide shift type
            first_slot_start, first_slot_end = relevant_slots[0]
            shift_type = 'day'
            if punch_time < first_slot_start:
                shift_type = 'night' if attendances_prev else 'day'
            elif first_slot_start <= punch_time < first_slot_end:
                shift_type = 'night' if attendances_prev else 'day'
            elif len(relevant_slots) > 1 and relevant_slots[1][0] <= punch_time < relevant_slots[1][1]:
                shift_type = 'day' if attendances_today else 'night'
            else:
                shift_type = 'day' if attendances_today else 'night'

            _logger.debug(
                "[SHIFT] Emp: %s Punch: %s Determined shift_type: %s (check_in=%s)",
                employee.id, punch_datetime, shift_type, is_check_in
            )
            return shift_type, relevant_slots


            #--------------------Cron Download------------------------------------#
            
    api.model
    def cron_download(self):
        """Cron job to download attendance from all configured devices"""
        devices = self.search([])
        _logger.info("Cron: Starting attendance download for %d device(s)", len(devices))
        for device in devices:
            try:
                device.action_download_attendance()
                _logger.info("Cron: Attendance downloaded for device %s", device.name)
            except Exception as e:
                _logger.error("Cron: Failed to download attendance for device %s: %s", device.name, str(e))


    # ---------------- Attendance Download ---------------- #

    def action_download_attendance(self):
        start_time = time.time()
        _logger.info("Downloading attendance...")

        zk_attendance = self.env['zk.machine.attendance']
        hr_attendance = self.env['hr.attendance']

        today = fields.Date.today()
        start_date = datetime.date(2025, 8, 29)
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

                # Group attendance by employee
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
                        zk_attendance.create({
                            'employee_id': employee.id,
                            'device_id_num': att.user_id,
                            'attendance_type': str(getattr(att, 'status', '1')),
                            'punch_type': str(getattr(att, 'punch', '0')),
                            'punching_time': punching_time,
                            'address_id': info.address_id.id
                        })
                    grouped_punches.setdefault(employee.id, []).append(local_dt)

                for emp_id, punches in grouped_punches.items():
                    punches = sorted(punches)
                    employee = self.env['hr.employee'].browse(emp_id)
                    for punch in punches:
                        if punch.tzinfo is None:
                            punch = device_tz.localize(punch)
                        shift_type, slots = self._select_shift_type(employee, punch)
                    
                        if shift_type is None or slots is None:
                            continue  # skip processing this punch

                        if shift_type == 'day':
                            first_start, first_end = slots[0]
                            second_start, second_end = slots[1] if len(slots) > 1 else (None, None)

                            if punch.time() <= first_end:
                                prev_att = hr_attendance.search([
                                    ('employee_id', '=', emp_id),
                                    ('check_out', '=', False),
                                    ('check_in', '>=', fields.Datetime.to_string(
                                        datetime.datetime.combine(punch.date(), datetime.time.min).astimezone(pytz.utc)
                                    )),
                                    ('check_in', '<', fields.Datetime.to_string(
                                        datetime.datetime.combine(punch.date(), datetime.time.min).astimezone(pytz.utc)
                                    )),
                                ], order="check_in desc", limit=1)


                                if not prev_att:
                                    # No active attendance → Check-in
                                    result = self._handle_same_day_hour_duplicate(hr_attendance, emp_id, punch, is_check_in=True)
                                    if result == 'new':
                                        hr_attendance.create({
                                            'employee_id': emp_id,
                                            'check_in': fields.Datetime.to_string(punch.astimezone(pytz.utc))
                                        })
                                else:
                                    # Active attendance found → treat as check-out
                                    if prev_att.check_in.time() != punch.time() and prev_att.check_in.time() < first_end:
                                        result = self._handle_same_day_hour_duplicate(hr_attendance, emp_id, punch, is_check_in=False)
                                        if result == 'new':
                                            prev_att.write({'check_out': fields.Datetime.to_string(punch.astimezone(pytz.utc))})

                            elif second_start and first_end < punch.time() <= second_end:
                                # Check-out logic
                                prev_att = hr_attendance.search([
                                    ('employee_id', '=', emp_id),
                                    ('check_out', '=', False),
                                    ('check_in', '!=', False),
                                    ('check_in', '>=', fields.Datetime.to_string(datetime.datetime.combine(punch.date(), datetime.time(0,0))))
                                ], order="check_in desc", limit=1)

                                if prev_att:
                                    result = self._handle_same_day_hour_duplicate(hr_attendance, emp_id, punch, is_check_in=False)
                                    # Only create a new check-out if result == 'new'
                                    if result == 'new':
                                        prev_att.write({'check_out': fields.Datetime.to_string(punch.astimezone(pytz.utc))})
                                    # If result == 'updated', do not create a new record, the check-out has been updated already!
                                else:
                                    result = self._handle_same_day_hour_duplicate(hr_attendance, emp_id, punch, is_check_in=True)
                                    if result == 'new':
                                        hr_attendance.create({
                                            'employee_id': emp_id,
                                            'check_in': fields.Datetime.to_string(punch.astimezone(pytz.utc))
                                        })

                            elif second_end and punch.time() > second_end:
                                prev_att = hr_attendance.search(
                                    [('employee_id', '=', emp_id), ('check_out', '=', False)],
                                    order="check_in desc", limit=1
                                )
                                if prev_att:
                                    result = self._handle_same_day_hour_duplicate(hr_attendance, emp_id, punch, is_check_in=False)
                                    if result == 'new':
                                        prev_att.write({'check_out': fields.Datetime.to_string(punch.astimezone(pytz.utc))})
                                    # If result == 'updated', do not create a new record, the check-out has been updated already!
                                else:
                                    result = self._handle_same_day_hour_duplicate(hr_attendance, emp_id, punch, is_check_in=False)
                                    if result == 'new':
                                        hr_attendance.create({
                                            'employee_id': emp_id,
                                            'check_in': False,
                                            'check_out': fields.Datetime.to_string(punch.astimezone(pytz.utc))
                                        })

                        else:  # Night shift
                            # ... (Apply same pattern for night shift as above!)
                            shift_start = slots[1][0]
                            shift_end = slots[0][1]
                            shift_check = slots[1][1]

                            punch_date = punch.date()
                            shift_start_dt = datetime.datetime.combine(punch, shift_start)
                            shift_check_dt = datetime.datetime.combine(punch, shift_check)
                            prev_day = punch.date() - datetime.timedelta(days=1)

                            shift_start_dt = device_tz.localize(shift_start_dt)
                            shift_check_dt = device_tz.localize(shift_check_dt)

                            if (shift_start_dt - datetime.timedelta(hours=2)) <= punch < shift_check_dt:
                                result = self._handle_same_day_hour_duplicate(hr_attendance, emp_id, punch, is_check_in=True)
                                if result == 'new':
                                    hr_attendance.create({
                                        'employee_id': emp_id,
                                        'check_in': fields.Datetime.to_string(punch.astimezone(pytz.utc)),
                                    })
                                # If result == 'discard', do nothing
                            else:
                                prev_att = hr_attendance.search([
                                    ('employee_id', '=', emp_id),
                                    ('check_out', '=', False),
                                    ('check_in', '>=', fields.Datetime.to_string(
                                        datetime.datetime.combine(prev_day, datetime.time.min).astimezone(pytz.utc)
                                    )),
                                    ('check_in', '<', fields.Datetime.to_string(
                                        datetime.datetime.combine(punch_date, datetime.time.min).astimezone(pytz.utc)
                                    )),
                                ], order="check_in desc", limit=1)

                                if prev_att:
                                    result = self._handle_same_day_hour_duplicate(hr_attendance, emp_id, punch, is_check_in=False)
                                    if result == 'new':
                                        prev_att.write({'check_out': fields.Datetime.to_string(punch.astimezone(pytz.utc))})
                                    # If result == 'updated', do not create a new record, the check-out has been updated already!
                                else:
                                    result = self._handle_same_day_hour_duplicate(hr_attendance, emp_id, punch, is_check_in=False)
                                    if result == 'new':
                                        hr_attendance.create({
                                            'employee_id': emp_id,
                                            'check_in': False,
                                            'check_out': fields.Datetime.to_string(punch.astimezone(pytz.utc))
                                        })

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
        return {
            'type': 'ir.actions.act_window',
            'name': 'Attendance Overview',
            'res_model': 'zk.machine.attendance',
            'view_mode': 'tree,form',
            'domain': [
                ('punching_time', '>=', fields.Date.to_string(start_date)),
                ('punching_time', '<=', fields.Date.to_string(end_date))
            ],
            'context': {'search_default_group_by_employee_id': 1}
        }


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

   