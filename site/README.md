# relic5's public page

https://relic5.buildwithoracle.com/ — one static `public/index.html` (no JavaScript, no network calls, fonts in
`public/fonts`, SIL OFL) served by the `relic5-site` Worker. Same shape as relic-scan's page
(relic4-scan `site/`, relic.buildwithoracle.com).

The page is public; the hub is private. So it carries no real counts, machine names, session titles, addresses or
screenshots: the pictures are hand-drawn SVG with made-up points, and the page says so.

Deploy from this folder on m5 (its Cloudflare login; `custom_domain` makes the DNS record and certificate):

    npx -y wrangler@4 deploy

First deployed 2026-10-24 23:14 +07 (version 5f6d35ce), with Nat's go.
