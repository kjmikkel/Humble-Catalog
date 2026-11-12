---
title: "Humble's 2026-11 Next.js redesign: public pages ported, order API and login are gone"
author: Mikkel
date: 2026-11-12
branch: fix/humble-redesign-public
cost: { minutes: 17, tokens: 188189 }
id: l-34afafd1
scope: repo
status: active
touches:
  - tests/test_bundle_preview.py
  - humble_catalog/bundle_preview.py
---

## Decided
- Bundle page and /books,/games listings now carry data only in the RSC flight payload (`self.__next_f.push([1,"..."])`). `bundle_preview.fetch_bundle` adapts the new `bundlePage` object into the OLD bundleData shape so `preview()` and its tests stay the spec; `live_bundles` reads product objects (`productKey` + `url`).
- Item `key` is `<machine_name>_<bundle>_<kind>`; `machine_name()` strips the last two segments. Verified against every live book bundle: full key never matches the catalog, stripped key matches as well as title matching.

## Watch out
- Flight `T` rows are length-prefixed in UTF-8 BYTES with no trailing newline; `_rows` walks bytes. Cumulative tiers reference earlier items as `$e:...:bundlePage:tiers:I:bundleItems:J` strings.
- NOT fixed (needs the owner to log in on the new site first): `/api/v1/user/order` and `/api/v1/order/{key}` answer 404 HTML even anonymously; `/login` is 404; the saved `_simpleauth_sess` reads `anonymous` at `/api/auth/session-status`; `/membership/home` 307s to `/membership` without `webpack-subscriber-hub-data`. So `extract`/`update`/`login`/Choice preview are all broken, and `logged_in()` can never return True. No library endpoint appears in the library page's JS chunks; the library page is a client-rendered shell.
- Probe live structure by printing key names and counts only, never titles from authenticated responses.
