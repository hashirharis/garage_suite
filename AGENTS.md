# Garage Suite development

- Target Odoo 19; shared operational models belong to `garage_core`.
- Edition/application modules compose capabilities by dependencies; Pro must inherit shared records.
- Use `suite_theme` (`../suite_theme`) for backend styling and visible Suite branding.
  New Suite application modules should depend on `suite_theme`, directly or through
  their edition dependency. Do not create another application-specific backend theme.
- Keep domain counts and dashboard drill-downs consistent, with ACLs and record rules
  enforced under the current user; never use `sudo()` for dashboard aggregates.
- Preserve SRS identity, approval, quality and release controls on server methods.
- Validate module installation and relevant tests using `compose.test.yml`; verify
  JavaScript and visual changes in the browser as well as Python/XML installation.
