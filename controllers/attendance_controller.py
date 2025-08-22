# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request

class HrAttendanceRealtimeController(http.Controller):

    @http.route('/attendance/realtime', type='json', auth='user')
    def attendance_realtime(self):
        """Return last 10 attendance records for the logged-in employee."""
        employee = request.env.user.employee_ids[:1]
        if not employee:
            return {'error': 'No employee linked to current user'}

        attendances = request.env['hr.attendance'].search(
            [('employee_id', '=', employee.id)],
            order='check_in desc',
            limit=10
        )

        result = []
        for att in attendances:
            result.append({
                'id': att.id,
                'check_in': att.check_in,
                'check_out': att.check_out,
            })
        return result
