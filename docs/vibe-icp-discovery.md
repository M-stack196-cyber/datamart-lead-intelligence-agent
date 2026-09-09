# Datamart Vibe ICP discovery

Discovery searches the United States first, then the UAE as a secondary market.
It requests companies with 1–50 employees, the target buyer titles,
priority industry categories, and overlapping revenue buckets above $500K.
The provider's highest matching bucket extends to $25M; local admission rejects
known revenue over $20M. Email is not a discovery or admission requirement.

The v1 prospect endpoint does not document a company ownership filter. Private
ownership is checked locally when returned; unknown ownership requires review.
Provider filters are targeting criteria, not evidence that returned rows satisfy
an attribute. Missing firmographics stay unknown.

Before enrichment and again before ingest, the deterministic prefilter excludes
incomplete identities, weak/social company URLs, excluded business categories,
wrong geography, non-buyers, and known out-of-range firmographics. Rejection
reasons are returned in cycle warnings and logged without raw profile contents.
Rejected rows are not stored by the discovery pipeline. Existing rejected records
are not deleted.

Plausible contacts with missing size, revenue, industry, B2B model, private
ownership, geography, or software need are retained for review. Qualified contacts
must satisfy these checks and all existing scoring hard stops. Numeric scores
remain evidence-based; the Vibe disposition applies the admission policy without
inventing points for missing growth or buying-behavior information.

The requested limit counts new stored accepted contacts (qualified plus review).
Discovery pages through at most 10 times that limit in provider candidates,
backfilling rejects and duplicates, reserving approximately 20% of the search budget
for UAE fallback when US results do not fill the limit, with pages and ingest batches of at most 100.
The existing database identity locks/indexes protect concurrent and repeated
intake. In-run identity tracking avoids repeated enrichment of identical rows.
A shortfall is reported when results or the search budget are exhausted. This
cannot guarantee 70–100 suitable prospects when the provider lacks coverage.
The existing daily scheduler and configured limit remain in control; manual runs
are separately capped runs, not a shared calendar-day quota.

Only qualified contacts with stored supporting evidence receive automatic drafts.
The existing draft RPC stores status `draft`, with no reviewer and no review date;
company members must review through the existing approval workflow. This pipeline
does not call delivery services.

Provider reference: https://developers.explorium.ai/reference/prospects/fetch_prospects

## Tightened production quality policy

The gate checks company names, titles, domains, and URL paths for education,
training, creator/media/personal-brand, agency, event/community, nonprofit,
government, and speculative/gambling categories. The supplied production
counterexamples are explicit negative examples in `EXCLUDED_BRANDS`; there is no
positive company allowlist. Course platforms and social link hubs are weak URLs.
A standalone domain passing these rules is not proof of B2B activity: sparse
candidates explicitly require manual ICP and website verification.

Outside-US/UAE contacts are rejected. There is no provider-controlled
opportunistic override. Missing firmographics produce the reasons
`Missing company size/revenue/industry data`,
`Good decision-maker title but sparse company data`, and
`Needs manual verification against Datamart ICP`.

Vibe fit scores total 100 available points: title 15, geography 15, independent
website 10, target company/product signals 20, B2B signals 10, size 10, revenue 10,
private ownership 5, defined software need 5. Missing attributes earn no points;
hard stops zero the fit score. Every component appears in stored evaluations.
Worker re-enrichment uses the same Vibe policy.

Deploy `20260909112152_tighten_vibe_person_identity.sql` before the backend update.
It replaces business-only uniqueness with indexed person-level lookups for
prospect ID, business ID + person, LinkedIn URL, website + person, and company
name + person. URL comparison ignores scheme, `www.`, tracking queries,
fragments, percent encoding, and trailing slashes. Name comparison ignores case,
repeated whitespace and punctuation. Existing duplicate records are retained;
new discovery matches them instead of inserting more. Different buyers at one
company are separate leads. The serialized RPC returns `duplicates` and a
`duplicate` flag per mapping, without changing existing lead review state.
Duplicate mappings are excluded from review output and draft generation.

The real-PostgreSQL tests accept only a local `/tmp` socket through
`VIBE_TEST_PG_SOCKET` (port 55439), create their own isolated database, apply the
migration, test all five identities and concurrent calls, then drop that test
database. With no test socket configured, those integration tests are skipped.
