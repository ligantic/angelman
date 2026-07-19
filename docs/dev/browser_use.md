# Local Browser Access

Use this runbook when opening the local TRRF registry in the built-in browser.

## Start the Registry

If the local registry is not already running, run the VS Code task **Django: Start debug Compose** from the `trrf` workspace. It starts the `runserver` service and publishes the registry on port `8000`.

## Open the Login Page

The browser automation runs outside the Compose DNS namespace, so `runserver`
does not resolve there. It also cannot use the dev container's loopback address.
Get the Docker host gateway from the dev container:

```sh
ip route show default | awk '{print $3}'
```

Open `http://<gateway>:8000/account/login` in the built-in browser. For example,
the gateway is commonly `172.19.0.1`, giving
`http://172.19.0.1:8000/account/login`.

The debug Compose override permits the gateway Host header. This is intentionally
limited to the local debug profile; non-debug deployments retain their configured
`ALLOWED_HOSTS` validation.

## Debug Outgoing Email

The local Compose stack starts smtp4dev with `runserver`. It captures development emails instead of delivering them externally.

Open the smtp4dev message UI through the same gateway at:

```
http://<gateway>:15000
```

Query captured messages through its API at:

```
http://<gateway>:15000/api/messages
```

Within Docker Compose, Django sends email to `smtp4dev:25`. smtp4dev's published host ports default to `15000` (web/API), `12525` (SMTP), and `13143` (IMAP). Override them before starting the stack with `SMTP4DEV_WEB_PORT`, `SMTP4DEV_SMTP_PORT`, or `SMTP4DEV_IMAP_PORT` if one is already in use.

To verify delivery from the local Django container and assert the API recorded the message, run:

```sh
docker compose -f docker-compose.yml -f docker-compose-debug.yml exec -T -w /app/rdrf runserver python manage.py shell --settings=rdrf.settings -c "from django.core.mail import send_mail; assert send_mail('smtp4dev smoke test', 'Local SMTP capture is working.', 'test@xxx.local', ['recipient@example.local']) == 1"
docker compose -f docker-compose.yml -f docker-compose-debug.yml exec -T runserver python -c "from urllib.request import urlopen; assert 'smtp4dev smoke test' in urlopen('http://smtp4dev/api/messages').read().decode()"
```

## Development Administrator

The local administrator is configured with:

- Username: `admin`
- Email: `admin@localhost`
- Password: `admin`

The registry login page labels its identifier field **Email Address**.

## Seed A Development Database

The debug stack can initialize generic development data, import the GASR registry
definition, and create deterministic participant scenarios. Seeding is disabled
unless explicitly enabled.

For a fresh or disposable database, start the debug stack with:

```sh
cd rdrf
ENABLE_REGISTRY_SEEDING=1 docker compose -f docker-compose.yml -f docker-compose-debug.yml up -d --build --force-recreate runserver
```

The canonical GASR definition is `angelman.yaml` in the workspace root. Debug
Compose mounts it read-only at `/registry-definitions/angelman.yaml`. The reusable
Django command accepts any registry definition:

```sh
ENABLE_REGISTRY_SEEDING=1 python manage.py seed_dev_database \
	--registry-file /path/to/registry.yaml
```

The command loads the `DEV` initial-data dataset, imports an absent registry, and
creates these deterministic states:

- `signup-pending`: inactive account without a participant record
- `account-active`: activated account without a participant record
- `onboarding`: participant without registry consent answers
- `consented-no-history`: consented participant without longitudinal history
- `one-history-future-alert`: one longitudinal entry and one future alert
- `many-history-due-alert`: three longitudinal entries and one overdue alert

Seeded usernames begin with `dev-seed-<registry-code>-` and use the local-only
password `development-only`. Re-running the command updates the same records.

If the database registry version matches the YAML, definition import is skipped.
A version mismatch fails without changing the definition. After backing up both
databases, an intentional update requires both flags:

```sh
ENABLE_REGISTRY_SEEDING=1 python manage.py seed_dev_database \
	--registry-file /path/to/registry.yaml \
	--update-existing --confirm-update
```

For container startup, set `REGISTRY_SEED_UPDATE_EXISTING=1` alongside
`ENABLE_REGISTRY_SEEDING=1` to supply those update flags. Seeding is always
rejected when Django is configured for production.