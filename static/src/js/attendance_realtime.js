/** @odoo-module **/

import { session } from 'web.session';
import bus from 'web.core.bus';
import { toast } from 'web.core';

document.addEventListener('DOMContentLoaded', function () {
    const channel = 'hr.attendance';
    
    bus.on(channel, null, function (message) {
        if (!message) return;

        const { employee_name, check_in, check_out } = message;
        let msg = `${employee_name} checked in at ${check_in}`;
        if (check_out) {
            msg = `${employee_name} checked out at ${check_out}`;
        }

        // Show notification toast
        if (typeof toast === 'function') {
            toast(msg, { type: 'success' });
        } else {
            alert(msg);
        }

        // Optional: reload Attendance view if open
        if (typeof odoo !== 'undefined' && odoo['web'] && odoo['web'].ClientActionManager) {
            // You could reload the hr.attendance tree view
        }
    });
});
