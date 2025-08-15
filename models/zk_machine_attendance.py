# -*- coding: utf-8 -*-
################################################################################
#
#    Cybrosys Technologies Pvt. Ltd.
#    Author: Ammu Raj (odoo@cybrosys.com)
#
#    You can modify it under the terms of the GNU AFFERO GENERAL PUBLIC LICENSE (AGPL v3), Version 3.
#
################################################################################

from odoo import api, fields, models
from odoo.exceptions import ValidationError
from datetime import datetime, timedelta

class ZkMachineAttendance(models.Model):
    """Model to hold data from the biometric device"""
    _name = 'zk.machine.attendance'
    _description = 'Attendance'
    _inherit = 'hr.attendance'

    # @api.constrains('check_in', 'check_out', 'employee_id')
    # def _check_validity(self):
    #     return



    device_id_num = fields.Char(string='Biometric Device ID',
                                help="The ID of the Biometric Device")
    punch_type = fields.Selection([
        ('0', 'Check In'), ('1', 'Check Out'),
        ('2', 'Break Out'), ('3', 'Break In'),
        ('4', 'Overtime In'), ('5', 'Overtime Out'),
        ('255', 'Duplicate')],
        string='Punching Type',
        help='Punching type of the attendance')
    
    attendance_type = fields.Selection([
        ('1', 'Finger'), ('15', 'Face'), ('2', 'Type_2'),
        ('3', 'Password'), ('4', 'Card'), ('255', 'Duplicate')],
        string='Category', help="Attendance detecting methods")

    punching_time = fields.Datetime(string='Punching Time',
                                    help="Punching time in the device")
    address_id = fields.Many2one('res.partner', string='Working Address',
                                 help="Working address of the employee")

    late_minutes = fields.Integer(string='Late Minutes', default=0)
    early_checkout_minutes = fields.Integer(string='Early Checkout Minutes', default=0)


   