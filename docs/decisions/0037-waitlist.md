# 0037 – The waitlist page, with a real referral line

**Date:** 2026-11-28
**Status:** Accepted

## Context
Launch is about a month away, on Android and iPhone at the same time. The app
has no website and no way to reach anyone it doesn't already have: the first Instagram
account was banned, and guests have no email. The marketing notes
(`lock-in-mode/marketing-knowledge.md`, rule 11) call for an owned audience: a waitlist,
linked from every bio, with a founding-member offer.

What the research says (Source 12 in the marketing notes):
- Visitors from your own bios and posts join far more often than cold traffic (about
  15–35% vs a few %). The page's job is to not lose warm visitors.
- Plain words win: on 41,000 Unbounce pages, copy at a 5th–7th grade reading level
  converted 11.1% vs 5.3% for college-level copy.
- Every extra form field costs signups: an email and one optional tap, nothing more.
- A **real** referral line (Robinhood: your place in line, moved up when friends join)
  turns each signup into a channel.
- A list nobody committed to doesn't buy (4,500 signups → 5 customers). Letting people in
  within a month keeps about 20% converting to paid; after 3 months, under 10%.

His choices (2026-11-28): in our own API, % off the first year + a badge, a referral line
whose top spots get early access, and a domain of his own. After the first version went
live he sharpened it (same day): launch is on both stores at once, his closed testers are
already sorted, so the page never mentions Android tests; the point is growing the list
before launch, and everyone who joins before launch gets the discount.

## Decisions

### 1. The page lives in the API, at `/`
- FastAPI serves `/` (one HTML template) and `/static/…` (css, js, icon, link-preview image,
  fonts). Same address as `/api/v1/waitlist`, so no CORS, and one deploy ships both.
  .NET: a Razor Page plus `UseStaticFiles` in the API project.
- **No third parties:** Rubik is self-hosted (the app's font, subset to Latin, 19 KB per
  weight, OFL licence alongside), no analytics script, no font CDN. A strict
  Content-Security-Policy (`'self'` only, no inline script or style, no framing) is on the
  page, so a mistake can't quietly load something from elsewhere.
- Everything the page promises comes from settings, never hard-coded in the HTML:
  `WAITLIST_FOUNDING_DISCOUNT_PERCENT` (50; 0 removes the offer from the whole page),
  `WAITLIST_TOP_SPOTS` (20), `WAITLIST_LAUNCH_LABEL` ("December 2026"),
  `WAITLIST_COUNT_SHOWN_FROM` (100), `WAITLIST_JOINS_PER_IP_PER_HOUR` (30).
- Light and dark follow the phone, with the app's palette (ADR 0036). The page is checked
  at 390×844 in both, and on desktop.

### 2. What the page says (and doesn't)
- Headline: "You keep starting Monday. This time, lock in." The pain one step away from
  "get fit" (Callaway), "you", and a contrast. Then three ordered things the app does,
  the shoulders hook from the best Short, "for you if…" lines, the perks and a short FAQ.
- **Only what's built:** plans are "built to train every" muscle head (the templates have a
  slot per head; short sessions drop the rear delt first, so not "every workout"); the
  streak is weekly; the "peek at Home" uses real features with example numbers (1/3 this
  week, so "1 more keeps your streak" is true at 2 a week). Tests guard these lines.
- **No fake urgency or crowd:** the count appears only once 100+ people are really on the
  list. "Only for people who join before launch" is the real condition of the offer.
- Sarcasm at habits ("downloaded three workout apps and opened them twice"), never at
  bodies (principle 7). No em dashes (house style).

### 3. One email, one optional tap
`POST /api/v1/waitlist {email, trains_at?, ref?, source?}`.
- The email is trimmed and lower-cased (a CHECK makes sure), unique. "Where do you train?"
  (gym / home / both) is optional: one tap that tells us which group is joining.
- The founding offer is the first thing in the form card ("Join before launch: 50% off…"),
  and after joining the share block leads with it: friends who join get the discount too,
  and each one moves you up. Growing the list is the page's main job.
- New → **201** with the spot, a public 8-character **link code** (no look-alike letters),
  and a private **key**, shown once. Only the key's sha256 is stored (like refresh tokens).
- Already on the list → **200** with their spot and **no key**, and nothing about the row
  changes: typing someone else's email can't rewrite their answer or who brought them. It
  does show that an email is on the list, which is fine for a waitlist.
- `ref` (a friend's code, any case) and `source` (`?s=tiktok`) are cleaned, and dropped if
  they aren't a plain code or tag: an old link never stops anyone joining.

### 4. The line
- Worked out on every read, never stored: **more friends first, then who joined first.**
  One friend moves you ahead of everyone with none. Friends count only while they're on
  the list (`referred_by_id` is `ON DELETE SET NULL`: if you leave, your friends stay).
- `GET /api/v1/waitlist/{code}` → `{position, friends_joined, on_list, top_spots, in_top}`.
  The code is in the share link, so anyone with your link can see your spot; that's all
  it shows.
- The top 20 get the app before everyone else (early access). The page says "in the top
  20 right now. Stay there…": spots move until early access goes out. **He needs a way to
  give it** (a pre-launch build or store early access) before launch day.
- **Gaming:** 20 joins a minute and 30 an hour per IP, and the top of the line is checked
  by hand before early access goes out (`waitlist_report --friends` lists who each one brought: a run
  of made-up emails is easy to spot). No email verification yet (no email service).

### 5. Leaving
`POST /api/v1/waitlist/leave {key}` → 204: the row is deleted for good. Only the key can
do it, so a shared link can never remove its owner. Someone who lost the key (cleared the
browser) can't leave from the page yet; they'll be able to from the launch email
(unsubscribe), and until then he can delete a row by hand on request.

### 6. Visits and the report
- The page sends `POST /api/v1/waitlist/visits {source}` once per browser per day:
  `waitlist_visits` counts per day and source. No IP, no cookie, no fingerprint.
- `uv run python -m lock_in_mode_api.waitlist_report [--days N] [--friends] [--csv file]`:
  the list size, visits → signups by source (the page's conversion rate, warm vs cold),
  friend-link signups, where they train, the front of the line, and a CSV of everyone for
  the launch email.

### 7. Sharing
After joining: the spot, the friend count, the link with **Copy**, **Send on WhatsApp**
(the launch market lives there) and the phone's own **Share** sheet where the browser has
one. A 1200×630 link-preview image (headline, no numbers that could go stale) so the link
looks right in WhatsApp, X and LinkedIn.

## What stays open
- **Sending email.** Nothing sends email yet: the launch email (and the founding offer's
  claim instructions it promises) needs a sender picked before launch, with unsubscribe.
- **Claiming the founding offer** in the app: Play promo/offer codes per email, or
  matching the email at Google sign-in (postponed). Decide with the free vs Pro split.
- **The Founding badge** is promised: the app needs it once accounts have emails.
- **The domain:** bought by him, then added to the Vercel project (docs/deploy.md §6).

## Consequences
- Two tables, not linked to `users`: account deletion doesn't touch them, and they're not
  in "Download my data" (they belong to an email, not an account).
- `/` is now a page, not a 404. The API docs leave the page out; the waitlist endpoints
  are in them, so the mobile app's generated types change (it doesn't call them).
- Vercel Hobby is for non-commercial use: a pre-launch waitlist is fine; Pro comes before
  the app charges (already planned).
