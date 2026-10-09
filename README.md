# Best Sports Bars NOLA sports news feeds

This repo publishes attributed sports headlines from a reviewed list of RSS and Atom sources. It started from `Sports_rss_feeds.zip` (October 2026). The catalog is data, not executable instructions: its sample scripts used hard-coded paths and did not fetch or publish feeds. `sources.json` preserves all 76 proposed sources; 65 that returned parseable RSS/Atom on October 9, 2026 are enabled. A verified Louisiana feed from Crescent City Sports brings the active total to 66.

GitHub Actions refreshes the output every three hours and deploys it to GitHub Pages. It commits a small weekly source-health record so the public repository stays active and its scheduled workflow is not disabled after 60 days of inactivity. Each result contains only a headline, date, source name, and link to the original publisher. No full article body is copied. A failed source is recorded in `index.json` and does not block other sources; a widespread failure stops publication rather than replacing the live data with an empty feed.

Published endpoints:

- [Feed directory](https://clawdaddy504.github.io/nola-sports-news-feeds/)
- [All sports RSS](https://clawdaddy504.github.io/nola-sports-news-feeds/all.xml) and [JSON](https://clawdaddy504.github.io/nola-sports-news-feeds/all.json)
- [New Orleans sports RSS](https://clawdaddy504.github.io/nola-sports-news-feeds/new-orleans.xml) and [JSON](https://clawdaddy504.github.io/nola-sports-news-feeds/new-orleans.json)
- `index.json` lists the additional source-category feeds and refresh health.

The New Orleans view includes Crescent City Sports plus a headline-keyword filter over the other sources. It is an editorial starting point, not a complete local-news index or a guaranteed team classifier. The other feeds group headlines by source category. Headlines older than four days are omitted. Updates depend on the upstream feeds and GitHub Actions scheduling, so publication can run later than the nominal three-hour interval.

To run locally: `python3 -m unittest discover -s tests -v` and `python3 build_feeds.py`. The generator uses Python's standard library and the `curl` executable. Generated JSON/XML in `docs` is ignored by Git; the Pages workflow builds and deploys fresh files directly.
