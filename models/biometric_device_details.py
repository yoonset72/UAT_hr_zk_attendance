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
        """Get merged working hours from all calendars for a specific date (weekday)."""
        calendars = employee.resource_calendar_ids or employee.resource_calendar_id
        if not calendars:
            return []

        weekday = punch_date.weekday()  # 0 = Monday
        attendance_lines = self.env['resource.calendar.attendance']

        for calendar in calendars:
            lines = calendar.attendance_ids.filtered(
                lambda a: int(a.dayofweek) == weekday
            )
            attendance_lines |= lines

        return attendance_lines.sorted('hour_from')


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
    
    @api.model
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


    def action_download_attendance(self):
        """
        Download raw punches for today only, store them in zk.machine.attendance (raw),
        then group punches per employee and create/update hr.attendance.
        Creates a record even if only check-in or only check-out exists.
        """
        import pytz
        import datetime
        import time

        start_time = time.time()
        _logger.info("++++++++++++ Downloading Attendance from Device (Today Only) +++++++++++++")

        zk_attendance = self.env['zk.machine.attendance']
        hr_attendance = self.env['hr.attendance']

        today = fields.Date.today()
        asia_rangoon_tz = pytz.timezone('Asia/Rangoon')

        def make_naive_utc(dt):
            if dt is None:
                return False
            if dt.tzinfo:
                dt = dt.astimezone(pytz.utc)
                return dt.replace(tzinfo=None)
            return dt

        def localize_if_naive(dt, tz):
            return tz.localize(dt) if dt.tzinfo is None else dt.astimezone(tz)

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
                grouped_punches = {}

                # Process only today’s attendance
                for att in all_attendance:
                    raw_ts = att.timestamp
                    local_dt = asia_rangoon_tz.localize(raw_ts) if raw_ts.tzinfo is None else raw_ts.astimezone(asia_rangoon_tz)
                    att_date = local_dt.date()
                    if att_date != today:
                        continue

                    employee = self.env['hr.employee'].search([('employee_number', '=', att.user_id)], limit=1)
                    if not employee:
                        user_name = next((u.name for u in users if u.user_id == att.user_id), "Unknown")
                        _logger.warning(f"Employee not found for user ID {att.user_id} ({user_name}). Skipping.")
                        continue

                    utc_dt = local_dt.astimezone(pytz.utc)
                    punching_time = fields.Datetime.to_string(utc_dt)

                    # Save raw punch if not exists
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

                    # Group punches by employee
                    grouped_punches.setdefault(employee.id, []).append(local_dt)

                # Process grouped punches for check_in/check_out
                for emp_id, punch_list in grouped_punches.items():
                    punch_list = sorted(punch_list)
                    employee = self.env['hr.employee'].browse(emp_id)

                    # Get working hours from all linked calendars
                    calendars = employee.resource_calendar_ids or employee.resource_calendar_id
                    attendance_lines = self.env['resource.calendar.attendance']
                    if calendars:
                        weekday = today.weekday()
                        for cal in calendars:
                            lines = cal.attendance_ids.filtered(lambda a: int(a.dayofweek) == weekday)
                            attendance_lines |= lines
                        attendance_lines = attendance_lines.sorted('hour_from')

                    # Fallback to default schedule if no calendar
                    if not attendance_lines:
                        attendance_lines = [
                            self.env['resource.calendar.attendance'].new({'hour_from': 8.75, 'hour_to': 12.0}),
                            self.env['resource.calendar.attendance'].new({'hour_from': 13.0, 'hour_to': 16.75}),
                        ]

                    # Convert to time slots
                    slots = [(self._float_hour_to_time(l.hour_from), self._float_hour_to_time(l.hour_to)) for l in attendance_lines]

                    check_in_dt = None
                    check_out_dt = None

                    for p_dt in punch_list:
                        p_time = p_dt.time()
                        matched = False

                        for start, end in slots:
                            if start and p_time <= start and not check_in_dt:
                                check_in_dt = p_dt
                                matched = True
                                break
                            if start and end and start <= p_time <= end:
                                if not check_in_dt:
                                    check_in_dt = p_dt
                                elif p_dt > check_in_dt:
                                    check_out_dt = p_dt
                                matched = True
                                break
                        if not matched and p_time >= slots[-1][1]:
                            check_out_dt = p_dt

                    vals = {}

                    if check_in_dt:
                        localized_in = localize_if_naive(check_in_dt, asia_rangoon_tz)
                        naive_in = make_naive_utc(localized_in.astimezone(pytz.utc))
                        vals['check_in'] = naive_in and naive_in.strftime('%Y-%m-%d %H:%M:%S')
                    else:
                        vals['check_in'] = None

                    if check_out_dt:
                        localized_out = localize_if_naive(check_out_dt, asia_rangoon_tz)
                        naive_out = make_naive_utc(localized_out.astimezone(pytz.utc))
                        if naive_out:
                            if vals.get('check_in'):
                                if vals['check_in'][:10] == naive_out.strftime('%Y-%m-%d'):
                                    vals['check_out'] = naive_out.strftime('%Y-%m-%d %H:%M:%S')
                                else:
                                    vals['check_out'] = None
                            else:
                                vals['check_out'] = naive_out.strftime('%Y-%m-%d %H:%M:%S')
                        else:
                            vals['check_out'] = None
                    else:
                        vals['check_out'] = None

                    # Update or create hr.attendance
                    attendance = hr_attendance.search([
                        ('employee_id', '=', emp_id),
                        ('check_in', '>=', fields.Datetime.to_string(datetime.datetime.combine(today, datetime.time.min))),
                        ('check_in', '<=', fields.Datetime.to_string(datetime.datetime.combine(today, datetime.time.max))),
                    ], limit=1)

                    if attendance:
                        attendance.write({'check_in': vals.get('check_in'), 'check_out': vals.get('check_out')})
                        _logger.info(f"Updated hr.attendance for {employee.name} on {today}")
                    else:
                        if vals.get('check_in') or vals.get('check_out'):
                            hr_attendance.create({
                                'employee_id': emp_id,
                                'check_in': vals.get('check_in'),
                                'check_out': vals.get('check_out'),
                            })
                            _logger.info(f"Created hr.attendance for {employee.name} on {today}")
                        else:
                            _logger.warning(f"Skipping attendance for {employee.name} on {today} — both check_in/check_out missing.")

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
        _logger.info(f"✅ Today’s attendance download completed in {total_time:.2f} seconds.")

        return {
            'type': 'ir.actions.act_window',
            'name': 'Attendance Overview',
            'res_model': 'zk.machine.attendance',
            'view_mode': 'tree,form',
            'domain': [
                ('punching_time', '>=', fields.Date.to_string(today)),
                ('punching_time', '<=', fields.Date.to_string(today)),
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