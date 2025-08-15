from odoo import api, models, fields
import logging

_logger = logging.getLogger(__name__)

class HrAttendance(models.Model):
    _inherit = 'hr.attendance'

    @api.constrains('check_in', 'check_out', 'employee_id')
    def _check_validity(self):
        _logger.info("Bypassing attendance validation check")
        return
    
    check_in = fields.Datetime(required=False)
