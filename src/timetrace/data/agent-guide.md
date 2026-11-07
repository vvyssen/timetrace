---
name: timetrace
description: Answer questions about how the user spends time on their Mac, iPhone and iPad (screen time, apps, projects, work vs leisure, late-night use) with the local `timetrace` CLI / MCP server, and help them tag uncategorized apps. Use for "where did my time go", "how long on WeChat yesterday", "what was I doing at 3pm", "tag this app".
---

# timetrace — time data for agents

`timetrace` reads the user's local ActivityWatch data (Mac windows + iPhone/iPad Screen Time),
classifies every interval and exposes it through a CLI (and the same operations as MCP tools).
Everything is local; nothing leaves the machine.

## Ground rules
1. Every number you report must come from a command's output. If a command fails, say so — never estimate.
2. Ask before writing: `timetrace tag` changes the user's rules. Show the proposed tags and get a yes first.
3. Start broad, then drill down: `timetrace summary --since 7d --group-by domain,evaluation --format json`.
4. Use `--format json` when you parse output yourself.

## The model
Each interval has `domain` > `subdomain` > `project`, plus an `evaluation` — the value of that time to the user:

| role | default zh / en label | meaning |
|---|---|---|
| create | 创造 / Create | valuable right away (producing work, decisions) |
| grow | 提升 / Grow | little value now, a lot later (learning, health, relationships) |
| keep | 保值 / Maintain | costs the user if skipped (errands, upkeep, replying) |
| leisure | 消遣 / Unwind | costs value in the short term (rest, entertainment, feeds) |

Labels are in the user's language — read them from `timetrace taxonomy --json` instead of assuming.
Shopping, food, travel and messaging are judged per sitting: a single continuous use longer than the
threshold in `duration_rules` counts as leisure, shorter ones as maintain. So one app can appear under
two evaluations — that is intended, not a bug.

## Commands
```
timetrace summary  --since 7d --group-by domain,evaluation   # where time went (fields: domain, subdomain,
                                                              # evaluation, project, app, device, date, hour, weekday)
timetrace timeline --date yesterday [--device iphone]        # what happened when
timetrace query    --since 30d --sql "select app, round(sum(seconds)/3600.0,2) h from intervals group by app order by h desc limit 10"
timetrace schema   # table columns, buckets, caveats       timetrace taxonomy --json   # labels and rules
timetrace suggest  --days 14 --format json                  # items that still need a tag
timetrace tag --bundle com.example.app --domain 生活 --subdomain 购物 --evaluation 保值
timetrace tag --mac-app "Some App" --domain 工作 --subdomain 开发 --evaluation 创造
timetrace tag --keyword my-repo --domain 工作 --subdomain 开发 --evaluation 创造 --project my-repo
timetrace doctor   # is data flowing? (ActivityWatch, Mac, iPhone/iPad importer, permissions)
```
Ranges: `--date 2026-11-03|today|yesterday`, `--from … --to …`, or `--since 7d|24h|90m|2w`. Default: last 7 days.
Devices: `--device all|mac|iphone|ipad`. Times are shown in local time.

## Caveats to mention when relevant
- iPhone/iPad data is app-level only: no page titles, no chat partners. Do not infer what was read or who was messaged.
- Mac data only exists since ActivityWatch was installed; iPhone/iPad data goes back as far as Screen Time kept it.
- Browser time without a site keyword stays under a generic "web browsing" project.

## Helping the user tag
The user can get the full hand-off prompt with `timetrace agent prompt`; the workflow it asks for:
1. `timetrace taxonomy --json` (labels in the user's language) and `timetrace suggest --days 14 --format json`
   — uncategorized apps and broadly-guessed windows, each with an `id`, time spent, sample titles and current guess.
2. Propose domain / subdomain / evaluation / project per item, most time first. Terminal and editor items are
   usually project folders; browser items are pages or sites. Ask the user when a project could be work, study
   or a personal interest — don't guess.
3. Show one table and wait for the user's confirmation or corrections.
4. Write with the id, which also keeps the tag scoped to the right apps (a project folder only in terminals and
   editors, a site only in browsers): `timetrace tag --id "<id>" --domain … --subdomain … --evaluation … --project …`
   (MCP: `tag` with `{"tags": [{"id": …, "domain": …, …}]}`). New subdomains are allowed. `--ignore` excludes an app.
5. Run `suggest` again and report what is left.
