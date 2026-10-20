# Responder Push Notifications (Web Push / VAPID)

Scope: emergency-offer notifications to verified, on-duty responders. Implemented in
`services/web_push.py`, `services/dispatch_service.py` (`_send_offer_push`), the
`/responder/push-*` endpoints, and `frontend/public/sw.js`.

## Honest status model

Each offer attempt records one `push_status`. It is never upgraded without evidence.

| Status                  | Meaning                                                                 |
|-------------------------|-------------------------------------------------------------------------|
| `NOT_CONFIGURED`        | VAPID env or `pywebpush` missing. No send attempted.                    |
| `SUBSCRIPTION_REQUIRED` | Responder has not registered a browser push subscription (or it expired).|
| `PERMISSION_DENIED`     | Browser denied notification permission (reported by the client).        |
| `SEND_FAILED`           | Push service rejected or was unreachable. Safe reason code only.        |
| `SEND_ATTEMPTED`        | Request accepted by the push service (HTTP 2xx). **Not device delivery.** |
| `DELIVERED`             | Reserved. Standard Web Push returns no delivery receipt; never produced. |

A dispatch offer is valid in-app regardless of push status. Push failure never blocks
the wave, accept, or decline.

## Environment variables (names only; values are secrets)

- `VAPID_PUBLIC_KEY` - served to the browser for `PushManager.subscribe`.
- `VAPID_PRIVATE_KEY` - server-only. Never sent to a client, logged, or put in an error.
- `VAPID_SUBJECT` - `mailto:` or `https:` contact URL.

Install the library: `pip install pywebpush` (listed in `requirements.txt`).

Generate a key pair once, with a tool such as `py-vapid` or `npx web-push
generate-vapid-keys`, and store the values in your secret manager.

## Flow

1. Responder goes ON_DUTY with explicit location-sharing consent (`POST /responder/duty`).
2. Responder taps "Enable background alerts". The browser asks for permission (user action only).
3. Frontend fetches the public key (`GET /responder/push/config`) and subscribes via the
   service worker `PushManager`, then posts it to `POST /responder/push-subscription`.
4. On an offer, the backend sends a payload with no victim PII and no location:
   title `HAVEN EMERGENCY REQUEST`, priority, distance, expiry, and the opaque dispatch id.
5. The service worker shows the notification. Clicking it opens `/responder?offer=<id>`.
   The page re-authenticates and fetches the offer from the backend. The notification
   grants no access by itself.
6. Going OFF_DUTY deletes the stored subscription. Expired subscriptions (404/410) are
   cleared automatically.

## Browser / PWA limitations (do not overstate)

- Background delivery depends on the browser, OS, notification permission, whether the
  app is installed as a PWA, and battery-optimisation policy.
- iOS delivers Web Push only to a home-screen-installed PWA on recent iOS versions.
- Android Chrome delivers while the browser is not force-stopped. Doze may delay delivery.
- No native ringtone or guaranteed alarm. A notification may be silenced or missed.
- No delivery receipt is available to the server. Authorities see `SEND_ATTEMPTED`,
  not "received".
- Foreground alerts use the in-app incoming-offer card on `/responder`.

## Production checklist

- Set `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_SUBJECT` in the backend secret store.
- Serve the frontend over HTTPS (service workers and push require a secure context).
- Confirm `public/sw.js` is served from the site root.
- Run `setup_indexes.py` (creates the 2dsphere index on `responders.current_location`).
- Verify a real device receives a test notification before relying on it operationally.
