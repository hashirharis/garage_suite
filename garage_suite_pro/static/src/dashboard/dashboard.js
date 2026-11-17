/** @odoo-module **/
import { registry } from "@web/core/registry";
import { deserializeDate, formatDate } from "@web/core/l10n/dates";
import { GarageDashboard } from "@garage_suite_basic/dashboard/dashboard";

export class GarageProDashboard extends GarageDashboard {
    static template = "garage_suite_pro.Dashboard";

    get insight() {
        return this.state.payload?.pro;
    }

    get profit() {
        return this.insight?.profitability;
    }

    measure(value) {
        return new Intl.NumberFormat(undefined, {
            style: "currency", currency: this.insight.currency,
        }).format(value);
    }

    monthLabel(date) {
        return formatDate(deserializeDate(date), { format: "MMM" });
    }

    get chartScale() {
        const values = this.profit.months.flatMap(month => [month.revenue, month.cost]);
        const floor = Math.min(0, ...values);
        const ceiling = Math.max(0, ...values);
        return { floor, span: ceiling - floor || 1 };
    }

    columnStyle(value) {
        const { floor, span } = this.chartScale;
        return `height:${Math.abs(value) / span * 100}%;bottom:${(Math.min(0, value) - floor) / span * 100}%`;
    }

    async openProfitability(domain = this.profit.domain) {
        const report = await this.action.loadAction("garage_suite_pro.action_profit");
        return this.action.doAction({ ...report, domain });
    }

    openSchedule() {
        return this.action.doAction("garage_suite_pro.action_tasks");
    }
}

const actions = registry.category("actions");
actions.add("garage_suite_pro.dashboard", GarageProDashboard);
actions.add("garage_suite_basic.dashboard", GarageProDashboard, { force: true });
