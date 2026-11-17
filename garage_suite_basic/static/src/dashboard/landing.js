/** @odoo-module **/
import { patch } from "@web/core/utils/patch";
import { WebClient } from "@web/webclient/webclient";

patch(WebClient.prototype, {
    _loadDefaultApp() {
        const garage = this.menuService.getApps().find(
            (app) => app.xmlid === "garage_core.menu_garage_root",
        );
        return garage ? this.menuService.selectMenu(garage) : super._loadDefaultApp(...arguments);
    },
});
