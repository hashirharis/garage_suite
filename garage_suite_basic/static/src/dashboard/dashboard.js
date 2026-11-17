/** @odoo-module **/
import { Component, onWillStart, useState, useExternalListener } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { user } from "@web/core/user";
import { _t } from "@web/core/l10n/translation";
import { deserializeDate, deserializeDateTime, formatDate, formatDateTime } from "@web/core/l10n/dates";

export class GarageDashboard extends Component {
    static template = "garage_suite_basic.Dashboard";
    static props = ["*"];
    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({ loading: false, error: "", period: "30", payload: null, canCreate: false, workspace: null });
        this.requestId = 0;
        onWillStart(async () => {
            this.state.canCreate = await user.hasGroup('garage_core.group_garage_user') || await user.hasGroup('garage_core.group_garage_receptionist');
            await this.load();
        });
        useExternalListener(document, "scm:dashboard-refresh", () => {
            if (!this.state.loading) this.load();
        });
    }
    async load() {
        const requestId = ++this.requestId;
        this.state.loading = true;
        this.state.error = "";
        try {
            const payload = await this.orm.call("garage.job.card", "get_dashboard", [this.state.period]);
            if (requestId === this.requestId) {
                this.state.payload = payload;
                if (!payload.workspaces.some(entry => entry.key === this.state.workspace)) {
                    this.state.workspace = payload.workspaces[0].key;
                }
            }
        } catch (error) {
            if (requestId === this.requestId) {
                this.state.error = error?.data?.message || _t("Unable to load the workshop overview. Try again.");
                this.state.payload = null;
            }
        } finally {
            if (requestId === this.requestId) this.state.loading = false;
        }
    }
    get workspace() {
        return this.state.payload?.workspaces.find(entry => entry.key === this.state.workspace);
    }
    trendHeight(count) {
        const max = Math.max(1, ...this.state.payload.trend.map(day => day.count));
        return Math.max(2, 100 * count / max) + "%";
    }
    shortDate(date) {
        return formatDate(deserializeDate(date), { format: "ccc" });
    }
    exportReports() {
        return this.action.doAction("garage_basic_reports.action_report_export");
    }
    changePeriod(event) {
        this.state.period = event.target.value;
        return this.load();
    }
    open(model, domain = [], name = _t("Workshop records")) {
        return this.action.doAction({ type: "ir.actions.act_window", name, res_model: model,
            views: [[this.state.payload?.list_views?.[model] || false, "list"], [false, "form"]], domain, context: {} });
    }
    openJob(id) {
        return this.action.doAction({ type: "ir.actions.act_window", res_model: "garage.job.card",
            res_id: id, views: [[false, "form"]] });
    }
    createJob() {
        return this.action.doAction({ type: "ir.actions.act_window", name: _t("New job card"),
            res_model: "garage.job.card", views: [[false, "form"]] });
    }
    date(value) { return value ? formatDateTime(deserializeDateTime(value)) : _t("Not scheduled"); }
    barWidth(count) { return `${Math.max(0, Math.min(100, count / (this.state.payload.total || 1) * 100))}%`; }
}
registry.category("actions").add("garage_suite_basic.dashboard", GarageDashboard);
