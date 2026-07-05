"""Demo dataset: two incident nights for the BlackoutOps demo.

LAST_NIGHT   - the "hangover" incident (July 4->5, 2026) the on-call engineer
               barely remembers. Ingested into dataset `incident_2026_07_05`.
HISTORICAL   - a similar incident from June 14, 2026, with its resolution.
               Ingested into dataset `incident_2026_06_14`. This is what makes
               "have we seen this before?" light up: recall connects the two
               through shared entities (redis-cache, eviction storm, checkout-service).

Each artifact is a realistic ops text fragment (alerts, Slack, shell history,
deploy log). Cognee's graph build links services, people, commands and causes
across fragments — which is exactly what a plain vector store can't do.
"""

LAST_NIGHT_DATASET = "incident_2026_07_05"
HISTORICAL_DATASET = "incident_2026_06_14"

LAST_NIGHT = [
    # --- monitoring alerts ---
    """[ALERT] 2026-07-05 02:47:11 UTC | severity=warning | source=prometheus
alertname=RedisMemoryHigh service=redis-cache cluster=prod-us-east
redis-cache memory usage at 94% of maxmemory (3.8GiB / 4.0GiB).
Eviction rate climbing: 1.2k keys/min. Runbook: RB-104.""",
    """[ALERT] 2026-07-05 03:12:36 UTC | severity=critical | source=prometheus
alertname=GatewayHigh5xx service=api-gateway cluster=prod-us-east
api-gateway 5xx rate 18.4% over 5m window (threshold 2%). Mostly HTTP 502
on POST /v1/checkout. Upstream: checkout-service. Runbook: RB-021.""",
    """[PAGE] 2026-07-05 03:15:02 UTC | PagerDuty incident #4412 triggered.
Escalation policy: prod-oncall-primary -> Devanshu. Ack at 03:16:47 from mobile.
Title: GatewayHigh5xx / api-gateway prod-us-east.""",
    # --- slack #incidents channel export ---
    """[SLACK #incidents] 2026-07-05
03:18 devanshu: ugh. gateway throwing 502s, redis at 94%. looking
03:21 devanshu: checkout-service latency p99 is 9s?? redis GETs timing out
03:24 priya: didn't we deploy checkout-service v2.14.1 at 02:30? check the deploy
03:26 devanshu: deploy log says yes, v2.14.1 at 02:30 by CI, change: "product page cache warming"
03:31 priya: v2.14.1 added cache warming that writes per-session keys with NO TTL. that would flood redis
03:33 devanshu: that matches, eviction storm started ~02:45. rolling back
03:41 devanshu: rollback to v2.13.0 done. also set redis maxmemory-policy to allkeys-lru as stopgap
03:49 devanshu: 5xx down to 0.4%. redis mem 71% and falling
03:55 priya: alerts cleared. write it down tomorrow... you won't remember any of this
03:56 devanshu: lol. sleep now""",
    # --- shell history recovered from the on-call laptop ---
    """[SHELL HISTORY] devanshu@oncall-mbp | 2026-07-05 03:18-03:44 UTC
03:18 kubectl -n prod get pods | grep -E 'gateway|checkout|redis'
03:19 kubectl -n prod logs deploy/api-gateway --since=30m | grep ' 502 ' | wc -l
03:22 redis-cli -h redis-cache.prod INFO memory
03:23 redis-cli -h redis-cache.prod INFO stats | grep evicted
03:27 kubectl -n prod rollout history deploy/checkout-service
03:33 kubectl -n prod rollout undo deploy/checkout-service --to-revision=41
03:38 redis-cli -h redis-cache.prod CONFIG SET maxmemory-policy allkeys-lru
03:41 kubectl -n prod rollout status deploy/checkout-service
03:44 kubectl -n prod logs deploy/api-gateway --since=5m | grep -c ' 502 '""",
    # --- deploy log ---
    """[DEPLOY LOG] service=checkout-service env=prod-us-east
2026-07-05 02:30:14 UTC deploy v2.14.1 by ci-bot (PR #892, author: marco)
Change summary: product page cache warming - precompute session-scoped
recommendation payloads into redis-cache on first page view.
2026-07-05 03:41:22 UTC rollback to v2.13.0 by devanshu (revision 41).""",
]

HISTORICAL = [
    """[POSTMORTEM] Incident 2026-06-14 "redis eviction storm" (PagerDuty #4188)
Impact: 22 min of elevated checkout latency, 3.1% failed checkouts.
Timeline: 21:04 RedisMemoryHigh on redis-cache -> 21:19 api-gateway 502 spike
-> 21:26 root cause found -> 21:40 recovered.
Root cause: promo-service June sale banner cached per-user variants in
redis-cache with no TTL, filling maxmemory and triggering an eviction storm
that evicted checkout-service session keys.
Fix: added 15-minute TTLs to promo cache keys; capped variant cardinality.
Lesson recorded: any service writing per-user/per-session keys into the shared
redis-cache MUST set TTLs and cap key cardinality. Shared-cache write policy
documented in RB-104 appendix. Owner: priya.""",
    """[SLACK #incidents] 2026-06-14
21:12 priya: redis-cache evictions spiking, checkout sessions getting dropped
21:20 marco: promo-service sale banner caches a variant per user, no TTL. thats new today
21:31 priya: adding TTLs + capping variants. gateway recovering
21:42 priya: resolved. postmortem tomorrow, lesson: shared redis needs TTL policy""",
]

# The postmortem the engineer files the morning after — the `improve` beat.
# Feeding the human-confirmed root cause back in is what makes memory ADAPT:
# next time redis evictions page anyone, recall serves the pattern + both fixes.
MORNING_POSTMORTEM = """[POSTMORTEM] Incident 2026-07-05 "checkout cache warming flood" (PagerDuty #4412)
Impact: 43 min elevated 5xx on api-gateway (peak 18.4%), checkout degraded.
Root cause: checkout-service v2.14.1 (PR #892) cache warming wrote per-session
recommendation keys into shared redis-cache with no TTL, filling maxmemory and
causing an eviction storm; evictions broke checkout session lookups, cascading
into api-gateway 502s.
Fix: rollback to v2.13.0 (03:41); stopgap maxmemory-policy=allkeys-lru (03:38).
Follow-ups: (1) re-land cache warming with 10-min TTLs and key cap,
(2) CI lint that rejects redis writes without TTL in shared cache namespaces,
(3) alert on eviction rate, not just memory %.
Pattern confirmed: SAME failure class as incident 2026-06-14 (promo-service) —
shared redis-cache + TTL-less per-user keys = eviction storm. This is now a
recognized recurring pattern; see RB-104 appendix."""
