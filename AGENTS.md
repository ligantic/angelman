# Agent Guidance

## Project Shape

- This workspace contains the shared RDRF platform and the Angelman (GASR)
	registry overlay.
- RDRF repository root: `rdrf/`. Django source root: `rdrf/rdrf/`.
- Run Django commands from `rdrf/` using `python3 rdrf/manage.py`.
- Angelman settings module: `angelman.settings`; canonical registry definition:
	`angelman.yaml` at the workspace root.
- Reusable platform changes belong in `rdrf/rdrf/rdrf/`. Angelman-specific
	branding and colour overrides belong in `angelman/angelman/`.

## Working Rules

- The worktree may be dirty. Never revert, reset, or overwrite unrelated user
	changes.
- Start from the nearest controlling view, template, test, or failing command.
	Keep changes narrowly scoped and preserve public URLs and YAML contracts.
- Prefer existing Django templates, Bootstrap, jQuery, Font Awesome, and RDRF
	CSS tokens over introducing a new framework or design system.
- Use `apply_patch` for source edits. Do not write files through shell
	redirection.

## Registry and Clinical Forms

- Registries are definition-driven. `angelman.yaml` controls forms, sections,
	CDEs, conditional rendering, headers, consent, dashboards, and reports.
- Do not change YAML to solve generic layout or rendering problems.
- Editable dynamic clinical forms are selected by
	`rdrf/rdrf/rdrf/views/form_view.py` and render through
	`rdrf_cdes/form.html`.
- Preserve clinical form DOM and JavaScript contracts: `#main-form`, section
	anchors, formset IDs/prefixes, field names/IDs, and `data-rdrf-*` hooks.
- For the current renderer-refactor status and next work, read
	[docs/clinical-form-ui-handoff.md](docs/clinical-form-ui-handoff.md).

## Validation

- `direnv` provides the local development environment. Do not manually set
	database or settings variables unless a command shows they are necessary.
- For clinical-form changes, run the focused suite from `rdrf/`:

	```sh
	python3 -m pytest rdrf/rdrf/testing/unit/cap07_clinical_form_tests.py -q --disable-warnings --tb=short
	```

- Django templates can produce false editor diagnostics when CSS or JavaScript
	contains template expressions. Prefer actual route rendering and focused
	tests when evaluating those files.
- Treat trailing AWS X-Ray shutdown logging separately from the pytest summary;
	inspect the test summary before diagnosing a failure.

## Local Runtime and Browser

For local registry browser access, smtp4dev debugging, debug Compose startup,
development credentials, and safe database seeding, read
[docs/dev/browser_use.md](docs/dev/browser_use.md) before using the browser or
changing local data.

- Creating a context/form instance through `/contexts/.../add/...` writes real
	local development data. Tell the user before doing it.
- Context creation requires the patient's working groups to be compatible with
	the target registry, even for superusers.
- Do not run registry reseeding or definition updates against a non-disposable
	database without explicit user approval.

## UI and Figma

- Keep reusable UI structure and behaviour in RDRF core; keep Angelman theme
	choices in the project stylesheet.
- Preserve existing DOM selectors before changing layout. Move direct
	JavaScript only as a separately tested change.
- When implementing from Figma, obtain design context first, adapt it to
	Django/CSS tokens, and never paste generated React or Tailwind output.