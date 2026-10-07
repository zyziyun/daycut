-- Reelfold usage counts (opt-in, anonymous). One row per event; nothing but the fields below is ever stored:
-- no IP address, no user agent, no file names, paths, text or keys. Days are UTC calendar days (YYYY-MM-DD).
-- Raw rows are kept 13 months (scheduled() in src/index.ts), the per-day aggregates (no install id) forever.

CREATE TABLE IF NOT EXISTS events (
  install_id   TEXT    NOT NULL,          -- random UUID made on the user's computer (resettable)
  day          TEXT    NOT NULL,          -- the day the event happened (client clock, day only)
  event        TEXT    NOT NULL,          -- app_open | first_batch_done | batch_done | export_done | publish_package
  version      TEXT    NOT NULL,          -- app version, e.g. 0.2.0
  os           TEXT    NOT NULL,          -- darwin | win32 | linux
  arch         TEXT    NOT NULL,          -- arm64 | x64
  locale       TEXT    NOT NULL,          -- the app's UI language: en | zh-CN | fr
  clips        INTEGER,                   -- batch_done
  formats      INTEGER,                   -- batch_done
  minutes_in   INTEGER,                   -- batch_done (rounded)
  count        INTEGER,                   -- export_done
  platform_count INTEGER,                 -- publish_package
  received_day TEXT    NOT NULL           -- the server's day (rate limit, retention)
);
CREATE INDEX IF NOT EXISTS events_day ON events (day);
CREATE INDEX IF NOT EXISTS events_install ON events (install_id, received_day);
-- app_open at most once per install per day; first_batch_done at most once per install
CREATE UNIQUE INDEX IF NOT EXISTS events_open_once ON events (install_id, day) WHERE event = 'app_open';
CREATE UNIQUE INDEX IF NOT EXISTS events_first_once ON events (install_id) WHERE event = 'first_batch_done';

-- one row per install: first and last day seen ("installs ever" survives the 13-month raw retention through
-- daily_agg 'new_install'; a row is deleted with the install's events, or 13 months after its last day)
CREATE TABLE IF NOT EXISTS installs (
  install_id TEXT PRIMARY KEY,
  first_day  TEXT NOT NULL,
  last_day   TEXT NOT NULL
);

-- the maintainer's own installs (and test machines): excluded from every number
CREATE TABLE IF NOT EXISTS internal_installs (
  install_id TEXT PRIMARY KEY,
  note       TEXT,
  added_day  TEXT NOT NULL
);

-- per-day totals without any install id, kept forever (rebuilt for recent days by the daily cron)
CREATE TABLE IF NOT EXISTS daily_agg (
  day      TEXT    NOT NULL,
  event    TEXT    NOT NULL,             -- an event name, or 'new_install' (installs first seen that day)
  version  TEXT    NOT NULL,
  os       TEXT    NOT NULL,
  locale   TEXT    NOT NULL,
  events   INTEGER NOT NULL,
  installs INTEGER NOT NULL,
  clips    INTEGER NOT NULL DEFAULT 0,
  minutes_in INTEGER NOT NULL DEFAULT 0,
  count    INTEGER NOT NULL DEFAULT 0,
  platform_count INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (day, event, version, os, locale)
);
