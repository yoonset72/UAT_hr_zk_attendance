from odoo import models, fields, api
import logging

_logger = logging.getLogger(__name__)

# ----------------------------------------------------
# Extend HR Employee to add an Employee Number field
# ----------------------------------------------------
class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    employee_number = fields.Char(
        string="Employee Number",
        help="Unique employee number for reference."
    )


# ----------------------------------------------------
# Extend HR Attendance to add related fields
# ----------------------------------------------------
class HrAttendance(models.Model):
    _inherit = 'hr.attendance'

    @api.constrains('check_in', 'check_out', 'employee_id')
    def _check_validity(self):
        _logger.info("Bypassing attendance validation check")
        return

    check_in = fields.Datetime(required=False)

    # Related fields from hr.employee
    employee_number = fields.Char(
        string='Employee Number',
        related='employee_id.employee_number',
        store=True
    )
    department = fields.Char(
        string='Department',
        related='employee_id.department_id.name',
        store=True
    )
    position = fields.Char(
        string='Position',
        related='employee_id.job_title',
        store=True
    )
