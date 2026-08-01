# Strategic Competitive Intelligence Review — post-M10

Written 2026-08-01, after M10 closed and `m10-baseline` was tagged. Evidence base:
`docs/research/COMPETITIVE-EVIDENCE.md` (every claim there is dated and cited; quality
tiers are labeled). This document is the interpretation layer: what the evidence means
for Jarvis, what to build, and what to refuse.

## 1. Executive Summary

The market validated Jarvis's category and, separately, validated its thesis. Two
products proved the category monetizes explosively — Manus ($100M ARR in 8 months, then
acquired by Meta for $2–3B) and Genspark ($100M in 9 months, ~$250M by month 12) — both
selling exactly what M10 finished building: agents that work in the background while
the owner is away. Independently, the design literature converged on Jarvis's founding
bet: Nielsen Norman Group named **trust, not capability, the central AI design problem
of 2026**, and enterprise selection in three separate product categories is decided by
governance and compliance rather than raw ability.

Jarvis is therefore not behind on strategy. It is behind on two specific things:
**people cannot watch it work**, and **it has never earned a dollar**. Everything below
follows from those two sentences.

The recommendation is to stop adding platform capability and spend the next milestone
making one existing business genuinely real while making the work visible. Trading
Intelligence — the original flagship — should wait for an evaluation harness and real
operating history, not because it is unbuildable but because the evidence says start
where the earning mechanism is proven, and no mechanism is proven by a platform that
has not yet earned.

## 2. Competitive Landscape — the four layers

Coverage conflates these constantly; separating them is the review's most useful act.

| Layer | Who | How money is actually made | Jarvis's relation |
|---|---|---|---|
| **A. Platforms** | Manus, Genspark, ChatGPT Agent/Work, Lindy, Relevance AI, 11x, Artisan | Subscriptions ($20–250/mo consumer; $2–7k/mo enterprise SDR) | Same architecture tier — but Jarvis is owner-operated, not sold. Not a competitor; a source of patterns. |
| **B. Operators** | Solo agencies, productized services | Retainers and outcome pricing ($10–30k/mo at ~80% automation, top decile) | **The tier Jarvis should imitate economically.** |
| **C. Narrators** | YouTube/Instagram "AI business" creators | Audience monetization + selling the playbook ($97 × 100 enrollees = $9.7k/launch) | The source of most $10k/mo claims. Not a model to copy. |
| **D. Infrastructure** | n8n (160k+ stars), LangGraph, Temporal, Letta/Mem0, ACP/AP2 | Open source, cloud tiers, standards | Jarvis consumes this layer (Temporal) and should keep consuming rather than rebuilding. |

**The honesty anchor, and it should govern every revenue projection we make:** 50% of
active indie operators earn under $1k/month; a February 2026 NBER study of 6,000 CEOs
found ~90% of firms report zero measurable impact from AI-employee deployments; and a
deliberate hunt for public P&Ls of autonomously-earning agents produced one concrete
case — $355 revenue against $400 of compute. Claims are abundant; receipts are scarce.

## 3. Philosophy, UX, Intelligence, Architecture — where Jarvis stands

**Philosophy.** Competitors sell capability and speed; Jarvis is built on the premise
that an autonomous system must be *governable and honest first*. The market moved
toward that position during M9–M10, not away from it.

**UX.** The literature's five mandatory agent patterns are planning visibility,
tool-use disclosure, memory surfacing, multi-step workflow tracking, and recovery
routing. Jarvis has the *facts* behind all five — decisions, audit, budgets, health,
lineage — and surfaces roughly two of them well. Manus's headline feature is watching
sub-agents work in real time; that is the emotional core of a $100M product, and it is
a rendering problem, not a capability problem.

**Intelligence.** Jarvis's judgment surface is deliberately small (the Executive is
mechanically forbidden from calling a model). Competitors are far more autonomous and
far less accountable. Memory is the real gap: Letta and Mem0 have made *experiential*
memory a product category; Jarvis remembers operations, not the owner.

**Architecture.** Durable execution, checkpointing, scheduling, and human-in-the-loop
are the properties production frameworks compete on — Jarvis sources them from Temporal
plus its own approval layer, which is a stronger substrate than most. Single-provider
model routing, single-runtime deployment, and no external alerting are the honest
weaknesses.

| Capability | Verdict |
|---|---|
| Governance, authority levels, approval gates | **Stronger** — nothing in the evidence file has a constitution |
| Audit trail / decision lineage / provable history | **Stronger** |
| Honest degradation and failure disclosure | **Stronger** (unknown-never-zero, proven live) |
| Budget enforcement and spend ceilings | **Stronger** |
| Durable long-running execution, scheduling | **Comparable** (post-M10) |
| Extensibility (business types as data) | **Comparable** |
| Work visibility while running | **Weaker** — the single biggest perception gap |
| Onboarding polish, integration breadth, model routing | **Weaker** |
| Experiential memory (owner preferences, house style) | **Missing** |
| Content generation pipeline | **Missing** |
| External integrations (social, commerce, payments) | **Missing** |
| Evaluation harness for judgment | **Missing** — and it gates Trading |
| Out-of-band alerting (host death) | **Missing** — the one operational blind spot |

## 4. Business automation and workflow comparison

Operators earn on *recurring deliverables with outcome pricing*: support resolution
($0.50–2.00/ticket), email sequences ($800–2,500 or $2–5k/mo), monitoring and reporting
retainers. Two of the four leading workflow platforms sell oversight as the
differentiator (Zapier's "governance that passes a security review", Relay.app's
approval-based workflows at $19/mo). The mechanism that pays is *reliable recurring
work with a human checkpoint* — which is precisely the shape of a Jarvis company.

Content and social automation carry a different profile: 68% of US searches now end
without a click, 71% of affiliate sites lost rankings in the March 2026 core update,
and both YouTube and TikTok now run formal AI-disclosure regimes with distribution and
monetization penalties. TikTok additionally renders API-posted video private until an
app audit passes. Counterweight: affiliate spend is up 11.3% and AI-search-referred
visitors convert at ~23× traditional search. **Content is now a quality game, not a
volume game** — which suits a platform that checks its own work and refuses to publish
without approval, and disqualifies the faceless-volume playbook entirely.

Commerce rails matured this year: ACP (OpenAI + Stripe) standardizes agent checkout and
AP2 (Google, donated to the FIDO Alliance) standardizes **cryptographic proof that an
agent acted with its user's consent** — Jarvis's approval model restated as an industry
protocol. But OpenAI scaled back in-chat purchasing in March: consumer agentic *buying*
is unsettled, while agentic *store operation* is not.

## 5. Premium experience analysis

Premium in this category is not visual polish; it is the feeling that a competent thing
is working on your behalf and will tell you the truth. Three ingredients recur in the
products that feel premium: you can watch the work happen; the system explains itself
without being asked; and it recovers visibly instead of failing silently. Jarvis has
the third, has the raw material for the second, and lacks the first entirely.

## 6. Highest-impact ideas worth adopting

1. **The Working View** — a live stream of what each company is doing right now,
   rendered from facts already recorded (decisions, capability dispatches, spend,
   audit). Highest perceived-value-per-unit-effort item in this review. It is Manus's
   headline feature, and for us it is a read model over existing tables.
2. **Dry-run / sandbox mode** — let a company do a full round with effects suppressed,
   so the owner can see what *would* happen. The trust literature names this as the
   pattern that converts skeptics; our approval architecture already has the seam.
3. **Experiential memory, governed** — an owner profile (house style, preferences,
   standing constraints) stored as approved configuration with provenance, never as
   model-authored policy. Adopt the concept from Letta/Mem0; refuse their "agent edits
   its own memory" freedom, which would violate execute-policy-never-create-policy.
4. **Outcome framing for business types** — types should be described and measured by
   the outcome they deliver, matching how the paying market actually buys.
5. **Disclosure compliance as a policy primitive** — platform AI-labeling regimes are
   real and penalized; make disclosure a contract-level requirement any publishing type
   inherits, exactly as the affiliate type already handles affiliate disclosure.
6. **ACP/AP2 literacy for the eventual commerce module** — build toward the consent
   proof standard rather than a bespoke checkout.

## 7. Ideas we should reject, and why

- **Selling Jarvis as SaaS (Layer A).** A different company with a different surface
  area. The mission is an operating system for the owner's businesses.
- **Conversational multi-agent frameworks** (CrewAI/AutoGen-style agent chatter).
  Jarvis has deterministic orchestration on a durable engine; AutoGen is in maintenance
  mode; adding agent-to-agent chat would trade auditability for novelty.
- **Faceless content volume plays as the first business.** Post-AI-search economics,
  disclosure regimes, ban risk, and survivorship-biased claims. The quality path is
  open; the volume path is closing.
- **Computer-use / agentic browsing as a core execution path.** Even the best-funded
  consumer implementation is reviewed as "rougher than expected on agentic flows."
  Use APIs; keep browsing as a fallback, never a foundation.
- **A vector-memory layer everywhere.** Benchmarks show real accuracy/latency
  trade-offs; §14 forbids speculative scope. Add memory where a demonstrated need
  exists (owner profile), not as infrastructure.
- **Trading Intelligence first.** Highest-risk judgment surface, real money, and no
  evaluation harness yet. It is not cancelled — it is sequenced.

## 8. Prioritized recommendations

**R1 — Earn one real dollar, honestly.** Take an existing business type to real
distribution: a real site, real affiliate relationships, real analytics, publishing
under the approval gate that already exists. Small money is fine; *real* is the point.
This converts the platform from demonstrated to operating, produces the first honest
KPI data the census has been asking for since M9, and exercises budgets, approvals,
compliance, and scheduling against reality rather than fixtures.

**R2 — Build the Working View.** Make the work visible while it happens. Highest
premium-perception return in this review, and it is a rendering of facts we already
store.

**R3 — Ship the content spine with disclosure built in.** One generation pipeline
(brief → draft → self-check → approval → publish) that any future publishing type
inherits, with platform disclosure as a contract requirement. This is the shared
foundation under the owner's YouTube/TikTok/e-commerce directive — build it once.

**R4 — Owner memory, governed.** House style and standing preferences as approved
configuration with provenance.

**R5 — Evaluation harness.** The precondition on any judgment work, including Trading.
Build it before the first judgment model call, as M9 required.

**R6 — Out-of-band alerting.** A notifier that survives the host's death, closing the
one blind spot M10 named and could not close from inside.

## 9. Strategic evolution roadmap

- **M11 — Earn and See** (R1, R2, plus R6 if cheap). The milestone where Jarvis stops
  being a demonstration. Success criterion: a real company, publishing real work under
  approval, with revenue or its honest absence measured — and an owner who can watch it
  happen.
- **M12 — Modules** (R3, R4). The content spine, then the first new business type built
  on it, chosen by what M11's real data says converts. Commerce ahead of social if the
  ACP/AP2 rails keep maturing; social only where disclosure compliance is structural.
- **M13 — Judgment** (R5, then Trading tactical L2). Evaluation harness, sub-ceiling,
  lineage with its first producer; Trading enters as a governed judgment surface with
  operating history behind it rather than as a leap.

## 10. Final evaluation — the owner's three questions

**Would Jarvis, polished to its current roadmap, rank among the best AI operating
systems?** On governance, auditability, and honesty: yes, and arguably first — nothing
in the evidence file can prove what it did the way Jarvis can. On breadth, polish, and
integrations: no, and it should not try to win there. The defensible claim is narrow
and real: *the AI operating system you can actually trust with a business, because it
proves what it did and asks before it acts.*

**What would stop an experienced user choosing Jarvis over Claude, ChatGPT, Manus,
Genspark, Cursor, or Devin?** Three things, in order: they cannot see it work; it does
not yet do anything that makes money; and it has no onboarding path that gets a
stranger from install to a running company. The first two are R1 and R2. The third is
M12-era work and should not be attempted before there is something worth onboarding to.

**What would make someone say "I can't imagine running my business without Jarvis"?**
Not autonomy — everyone claims autonomy. It is the morning where the owner opens the
console and finds that four companies worked overnight, each one showing exactly what
it did, what it spent, what it decided and why, what it refused to do without
permission, and what it is waiting on — and every number is true, including the
uncomfortable ones. That is a product no competitor in this file can ship, because
they did not build the constitution first. **Jarvis did. It now needs to earn.**
