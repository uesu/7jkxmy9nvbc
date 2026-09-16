# Round 15: Reddit V3 archive enrichment and text repair

## Scope

Changes are limited to `testing area/reddit_main_v3test.py`, its proxy text
cleaner, offline smoke tests, and documentation. No workflow, secret, dependency,
cache, V1/V2 monitor, or production X/Twitter entrypoint changes are required.

Arctic Shift is optional: each native-mode fetch target gets a request with a
10-second timeout. Three consecutive errors disable archive requests for the
rest of that process. Empty archive results are normal misses, not outages.
The response must contain the requested post ID. Archive records can lag Reddit,
retain earlier versions of posts, and contain stale counts or expired media.
Fallback counts are explicitly labelled `archived counts` on the card.

Crossposts use the original's proxy/media while keeping the crosspost's title,
byline, and Read Post link. The crosspost notice points to the original. Ordered
archive galleries include animated images when their GIF source is available.
Existing proxy/redlib/RSS fallbacks remain in place. Only native mode gains the
archive source; the existing authenticated FULL MODE media path is unchanged.

## Differences from the pasted proposal

- Conservative cleanup preserves standalone valid Markdown links, title
  punctuation, usernames with trailing underscores/hyphens, and ordinary prose
  containing “submitted by”. Repairs are based on paired artifacts and never
  borrow an unrelated URL from the next line.
- The post's own YouTube URL is removed whether still bare or already converted
  to a URL-labelled Markdown link. Other links remain.
- Archive responses and nested gallery data are validated defensively.
- Structured archive text precedes flattened proxy descriptions when RSS text
  is absent. Archive counts are labelled instead of presented as live counts.
- No blanket claim is made that Arctic Shift is real-time or always reachable.
  No blanket claim is made that Reddit `fallback_url` or DASH files have audio.
  The existing video resolver/range check is reused; it does not verify audio
  tracks. Real Discord playback/audio needs manual validation.

## Automated validation

Run without secrets or network requests:

```sh
python -m compileall -q main.py "testing area" tests
python tests/test_smoke.py
git diff --check
```

The added fixtures are synthetic examples of the supplied response shapes,
not a recording of a live service check. Async tests replace all network
boundaries and exercise the actual resolver (including archive misses,
malformed data, circuit breaking, crosspost proxy paths, screenshot rejection,
gallery priority, and body precedence).

## Manual acceptance (not yet performed)

After reviewing the draft PR, use the V3 workflow's manual dispatch on this
branch with dry-run enabled. Confirm the selected ref is this PR's branch, not
`main`. Do not run a posting test against a live webhook by accident.

Suggested posts from the report:

- `AnantaLeaks/1wgjjvn`: original crosspost link, real video rather than a proxy
  screenshot; no bare v.redd.it body line.
- `Genshin_Impact_Leaks/1wfz61f`: six ordered media items, including three GIFs,
  if the archive still supplies the reported gallery.
- `WutheringWavesLeaks/1whe2tr`: repaired video links remain clickable.
- `AnantaLeaks/1whmgtm`: paragraphs retained and duplicate YouTube URL removed.

Dry-run payloads alone do not prove GIF animation or audio. Before merging,
validate those in a deliberately configured test Discord channel if desired.
Neither offline tests nor opening this PR sends Discord messages.
