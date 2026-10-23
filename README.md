# Social Media — Backend

The API behind Social Media: accounts and profiles, posts carrying photos,
video or audio, likes, comments, reshares, follows, notifications, and direct
messaging delivered over a WebSocket.

Django 6.1 and Django REST Framework on PostgreSQL 17, with Channels over Redis
for realtime chat and a swappable media backend that writes either to the local
filesystem or to Cloudinary.

## Running it

You need Python 3.12 or newer, plus PostgreSQL and Redis. The repository root
has a `docker-compose.yml` that brings up both with the credentials the
defaults expect:

```bash
docker compose up -d                # postgres on 5432, redis on 6379

python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env                # then set DJANGO_SECRET_KEY
.venv/bin/python manage.py migrate
.venv/bin/python manage.py runserver 8000
```

`manage.py` defaults to `config.settings.dev`; `wsgi.py` and `asgi.py` default
to `config.settings.prod`. `runserver` speaks ASGI because `daphne` is listed
ahead of `staticfiles` in `INSTALLED_APPS`, so the chat socket works in
development without a separate process.

Uploads land in `backend/uploads/` and are served by Django while `DEBUG` is on,
so the whole app runs with no third-party credentials. Point
`MEDIA_STORAGE_BACKEND` at `apps.media.storage.cloudinary.CloudinaryStorage` and
fill in the `CLOUDINARY_*` variables to switch providers; nothing else changes.

### Configuration

Every setting is read from `.env` through `django-environ`. `.env.example` lists
the ones you are likely to set.

| Variable | Default | Purpose |
| --- | --- | --- |
| `DJANGO_SECRET_KEY` | insecure dev key | Signs sessions and JWTs |
| `DJANGO_DEBUG` | `True` in dev, `False` in prod | Also decides whether Django serves `uploads/` |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1` | Ignored in dev, which allows everything |
| `POSTGRES_*` | `social_media` / `social` / `social` on `localhost:5432` | Database connection |
| `REDIS_URL` | `redis://localhost:6379/0` | Channel layer that carries chat events |
| `CORS_ALLOWED_ORIGINS` | `http://localhost:5173` | Browser origins allowed to call the API |
| `WEBSOCKET_ALLOWED_ORIGINS` | the CORS list | Origins allowed to open a socket; `*` disables the check |
| `MEDIA_STORAGE_BACKEND` | `…storage.local.LocalFileSystemStorage` | Import path of the storage provider |
| `CLOUDINARY_*` | empty | Required only when the Cloudinary backend is selected |
| `SITE_BASE_URL` | `http://localhost:8000` | Used to build absolute URLs for local uploads |

## Layout

```
backend/
├── config/
│   ├── settings/     base, dev, prod
│   ├── urls.py       every app mounted under /api/
│   ├── asgi.py       HTTP plus the origin-checked, JWT-authenticated socket
│   └── wsgi.py
└── apps/
    ├── core/            base model, domain errors, base repository, pagination
    ├── media/           media kinds, storage backends, upload orchestration
    ├── accounts/        custom user, registration, sign-in, profiles
    ├── posts/           posts, feeds, reshares
    ├── interactions/    likes and the follow graph
    ├── comments/        comments, their replies, and the likes on both
    ├── notifications/   what other people did to you, derived from those events
    └── chat/            conversations, messages, and the socket that delivers them
```

Every app is layered the same way and requests flow in one direction:

```
views.py          HTTP only: parse, delegate, serialize. No rules.
   ↓
services.py       Use cases and business rules. Raises domain errors.
   ↓
repositories.py   The only place that builds querysets.
   ↓
models.py         Schema.
```

A view never touches a queryset and a service never touches an HTTP object, so
the rules can be tested without a request and the persistence layer can change
without rewriting them. `signals.py` in `posts`, `interactions`, `comments` and
`notifications` keeps denormalized counters and notification rows in step with
the writes that cause them.

## How it fits together

**Auth is JWT.** Registration and sign-in return an access token (30 minutes), a
refresh token (14 days) and the user. Refresh tokens rotate. Every endpoint
requires `Authorization: Bearer <token>` except registration, sign-in, refresh
and the health check.

**Ids are numeric in the database and strings in JSON.** `BigAutoField` runs
past the range JavaScript represents exactly, so every serializer declares
`id = serializers.CharField(read_only=True)`.

**Errors have one shape.** Services raise `DomainError` subclasses
(`ResourceNotFound`, `PermissionDenied`, `InvalidInput`, `Conflict`,
`StorageFailure`) that know nothing about HTTP, and `api_exception_handler`
renders all of them — plus DRF's own validation errors — as
`{"error": {"code", "message", "details"}}`. A non-numeric id in a URL is
treated as a missing resource, so junk paths return 404 rather than 500.

**Feeds are cursor paginated.** A feed grows at the head, so offset paging would
shift rows between requests and repeat posts. The cursor orders by
`(-created_at, -id)`, and the id tiebreaker makes the ordering total. Pages
default to 20 and `?limit=` goes up to 50.

**Counters are denormalized and maintained with `F()` expressions** inside the
same transaction as the write that moved them, so concurrent likes cannot
clobber each other. They remain derivable from the underlying rows, and three
management commands rebuild them.

**Storage is a swappable strategy.** `MediaStorage` is an abstract contract with
`upload` and `delete`; `get_media_storage()` resolves the configured
implementation and services depend only on the abstraction. A single
`MediaAsset` table serves post attachments, chat attachments and avatars.
Uploads happen before any transaction opens and compensate by deleting what
already landed if a later file fails; deletions are scheduled with
`transaction.on_commit`, because a rollback cannot reach Cloudinary.

**Media kinds are an open registry.** `apps/media/kinds.py` holds one spec per
kind — MIME prefixes, extensions, size cap — and detection loops over the
registry instead of branching on type, so supporting a new kind means
registering a spec rather than editing existing code.

**Chat is written over HTTP and delivered over a WebSocket.** Messages are
posted to `/conversations/{id}/messages/` because attachments need a multipart
body and one write path is easier to keep correct than two; `ChatBroadcaster`
then publishes the serialized payload to one channel layer group per
participant. Delivery is best effort, since the message is already committed by
then. A client joins only the group named after its own user id, so one socket
serves every thread and no per-message access check is needed.

The rationale behind each of these lives in the module docstrings next to the
code — `apps/core/exceptions.py`, `apps/media/storage/base.py`,
`apps/chat/broadcast.py` and the model docstrings are the places to start.

## API

Everything is mounted under `/api/` and needs a bearer token unless marked
public.

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/auth/register/` | Create an account, returns a session (public) |
| `POST` | `/auth/login/` | Sign in, returns a session (public) |
| `POST` | `/auth/refresh/` | Exchange a refresh token (public) |
| `GET` `PATCH` | `/users/me/` | Read or edit your profile |
| `PUT` `DELETE` | `/users/me/avatar/` | Replace or remove your avatar |
| `GET` | `/users/{username}/` | Public profile |
| `GET` | `/users/{username}/posts/` | That user's posts |
| `POST` `DELETE` | `/users/{username}/follow/` | Follow or unfollow, returns fresh counts |
| `GET` | `/users/{username}/followers/`, `/following/` | Either side of the relationship |
| `GET` `POST` | `/posts/` | Feed, or publish (multipart: `caption`, repeated `files`) |
| `GET` `PATCH` `DELETE` | `/posts/{id}/` | Read, edit the caption, or delete |
| `POST` `DELETE` | `/posts/{id}/like/` | Like or unlike, returns fresh counts |
| `GET` | `/posts/{id}/likers/` | Who liked it |
| `POST` | `/posts/{id}/share/` | Reshare, optionally with a caption |
| `GET` `POST` | `/posts/{id}/comments/` | The thread under a post, or comment on it |
| `GET` `POST` | `/comments/{id}/replies/` | A comment's replies, or answer it |
| `POST` `DELETE` | `/comments/{id}/like/` | Like or unlike a comment |
| `DELETE` | `/comments/{id}/` | Withdraw your comment, or moderate your own thread |
| `GET` | `/notifications/` | Your notifications, newest first |
| `GET` | `/notifications/unread-count/` | Badge count |
| `POST` | `/notifications/{id}/read/`, `/notifications/read-all/` | Mark read |
| `GET` `POST` | `/conversations/` | Inbox, or open a thread with `{username}` |
| `GET` | `/conversations/{id}/` | One thread |
| `GET` `POST` | `/conversations/{id}/messages/` | History, or send (multipart: `body`, `reply_to`, repeated `files`) |
| `POST` | `/conversations/{id}/read/` | Clear the thread's unread count |
| `GET` | `/conversations/unread-count/` | Unread messages across every thread |
| `GET` | `/health/` | Liveness plus a database check (public) |

Limits: images 10 MB, video 200 MB, audio 50 MB. A post takes 10 attachments
and a 2200-character caption; a message takes 4 attachments, images and audio
only, and a comment is up to 1000 characters.

### WebSocket

Connect to `ws://host/ws/chat/?token=<access token>` — a browser cannot set an
`Authorization` header on a handshake, so the token travels in the query string.
An unusable token closes the socket with application code `4401`.

The server sends `{"type": "ready"}` once the client has joined its group, then
`message.created`, `conversation.read` and `typing` events. It accepts
`{"type": "ping"}` and
`{"type": "typing", "conversation": "<id>", "state": "start" | "stop"}`. Typing
is the only thing clients send up the socket and the only thing never stored.

## Tests

224 tests, no network and no Cloudinary: uploads are redirected to a scratch
directory or served by an in-memory storage double. A running PostgreSQL is
still required, and the channel layer is swapped for the in-memory one.

```bash
.venv/bin/python manage.py test
.venv/bin/python manage.py test apps.chat       # one app
```

Shared fixtures — `MediaRootTestCase`, `make_user`, and the PNG, audio and video
upload helpers — live in `apps/core/testing.py`.

## Management commands

Each recounts denormalized columns from the rows they are derived from, which is
worth doing if anything ever writes to those tables while bypassing the signals.
All three take `--dry-run`.

```bash
.venv/bin/python manage.py recount_post_stats       # like, share and comment counts
.venv/bin/python manage.py recount_comment_stats    # like and reply counts
.venv/bin/python manage.py recount_follow_stats     # follower and following counts
```
