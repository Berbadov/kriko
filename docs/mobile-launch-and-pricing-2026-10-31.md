# Kriko mobile: Play launch and pricing

Research date: 31 October 2026. Existing personal Play account; its creation date
and this app's production-access status are unknown. International availability
is a configurable choice, not an automatic consequence of uploading an app.
All financial examples below use USD before applicable sales tax/VAT.

## Recommendation

Make mobile the primary product: see a listing, ask by voice, understand the
product's fit, investigate the merchant, and decide what to buy. That direction
fits the screen assistant and voice features already built. It is a product
hypothesis, not evidence that customers will subscribe. Keep the desktop and
extension as companion surfaces and acquisition routes.

Offer two access routes:

1. **Use Kriko**: a simple paid hosted service, with a small introductory trial,
   monthly research allowances and optional top-up packs.
2. **Use my API keys**: free direct-provider access for technical users. They pay
   their providers. In this implementation that means Mercury plus DeepSeek,
   with an optional Mistral key for simple text requests, rather than arbitrary interchangeable agents.

Do not sell unlimited research or unlimited hourly price monitoring initially.
Treat compatibility and merchant checks as reasons to choose Kriko, rather than
positioning it as another general-purpose chatbot. Test one strong category
and English/Turkish shopping flows before broadening marketing.

## Play requirements and actual gaps

| Area | Requirement or decision | Kriko status / next action |
|---|---|---|
| Account | Identity and device verification; registration is $25 once | Existing personal account: check verification and package registration in Console. No assumption that another registration payment is needed. [Account setup](https://support.google.com/googleplay/android-developer/answer/6112435), [package registration](https://support.google.com/googleplay/android-developer/answer/16984799). |
| Testing | Personal accounts created after 13 November 2023 need at least 12 testers continuously opted in for 14 days, followed by a production-access application | An existing account is not automatically exempt. Check its creation date and this app's Console dashboard. [Testing rules](https://support.google.com/googleplay/android-developer/answer/14151465). |
| Countries | Choose production countries/regions, and configure subscription availability/prices for them | International is possible. A limited initial rollout can reduce language, merchant-data and support gaps. [Country targeting](https://support.google.com/googleplay/android-developer/answer/7550024). |
| Package | Produce an AAB, configure Play App Signing and maintain the signing identity | The delivered APK is for direct installation, not a Play-ready upload. Choose production signing deliberately; the current friend build uses the project's debug signing key. [App setup](https://support.google.com/googleplay/android-developer/answer/9859152). |
| Android target | New apps/updates must target API 36 from 31 August 2026 | Current generated target is 36. [Target requirement](https://support.google.com/googleplay/android-developer/answer/11926878). |
| Native compatibility | Support 16 KB pages on 64-bit devices; current guidance names 1 February 2027 as the update-release blocking date | Validate the actual packaged libraries and test on a 16 KB device/emulator; SDK version alone does not prove compliance. [Native page sizes](https://developer.android.com/guide/practices/page-sizes). |
| Billing | In-app digital AI access generally uses Play Billing, unless enrolled in an applicable regional exception | Add a real purchase/restore/manage-subscription flow, verified entitlements, refunds, cancellations and subscription renewal handling. Free BYOK does not itself sell an entitlement; charging to unlock BYOK features would be a digital purchase. The BYOK interpretation is an inference from the policy, not a named exemption. [Payments](https://support.google.com/googleplay/android-developer/answer/9858738). |
| Self-updates | Play policy does not allow `REQUEST_INSTALL_PACKAGES` for self-updating ordinary apps | Make a separate Play distribution configuration that removes GitHub APK installation and uses Play updates. Retain the direct APK updater only in the sideload distribution. [Install-package policy](https://support.google.com/googleplay/android-developer/answer/12085295). |
| Screens and voice | Declare actual foreground-service usage; provide required disclosure and consent before unexpected sensitive collection | The app uses MediaProjection/overlay and Android speech recognition, not AccessibilityService. Review the capture flow, explain provider uploads before collection, and prepare the FGS demonstration video. Do not claim accessibility-tool status merely because voice helps a parent. [FGS declarations](https://support.google.com/googleplay/android-developer/answer/13392821), [User Data](https://support.google.com/googleplay/android-developer/answer/10144311). |
| Privacy | Public privacy-policy URL plus in-app policy; accurate Data safety disclosures | Local history does not mean no collection: screenshots and questions go to providers. The current log is useful but does not replace consent. Account creation for the hosted service adds in-app and web account-deletion requirements. [Privacy policy](https://support.google.com/googleplay/android-developer/answer/10144311), [account deletion](https://support.google.com/googleplay/android-developer/answer/13327111). |
| AI safety | In-app reporting/flagging of offensive generated output | Add a Report answer action and a review/moderation process before the Play launch. [AI-content policy](https://support.google.com/googleplay/android-developer/answer/13985936). |
| Listing/review | Complete listing, screenshots, content rating, target audience, ads declaration, app access and review instructions | Give reviewers a reliable way to exercise paid/hosted features. Prepare these as Console submission materials. [App setup](https://support.google.com/googleplay/android-developer/answer/9859152). |

The current APK is a friend/test distribution. This research does not claim it
is ready for Play approval or that Play subscriptions have been implemented.

## Hosted access must change before charging

Currently a sealed trial bundle can supply owner provider keys on the phone,
and trial use is counted locally. That is useful for a controlled friend build,
but APK contents and local counters cannot protect a paid service.

Put the hosted provider keys and enforcement on a backend. The app sends an
authenticated request; the backend verifies entitlement, reserves a budget,
calls providers, records usage and settles credits. Deduplicate requests so a
retry does not grant or consume an entitlement twice. Handle pending purchases,
renewal/cancellation/refund events, and restore access on reinstall/new devices.
Keep BYOK calls direct when feasible; do not collect BYOK secrets just to meter
the hosted subscription. Google specifically recommends backend purchase
verification and sensitive logic. [Billing security](https://developer.android.com/google/play/billing/security).

Use provider spend limits, per-user monthly quotas, per-turn token/tool/time
caps and global daily budget alerts. Backend cost accounting can remain
mandatory for protecting spend while user-facing diagnostics remain off.
Cost telemetry need not contain raw screenshots or full private questions.

## Rate card used for planning

| Component | Planning rate | Current evidence |
|---|---:|---|
| Mercury 3 input/output | $0.20 / $0.70 per million tokens | Regular prices; the launch promotion is $0.10 / $0.35. We do not build the business around a temporary discount. [Inception rates](https://docs.inceptionlabs.ai/get-started/models). |
| DeepSeek Flash vision input/output | $0.30 / $1.20 per million tokens | Peak uncached rates; off-peak is half. Cache savings are not assumed. [DeepSeek rates](https://api-docs.deepseek.com/quick_start/pricing/). |
| DeepSeek Search or Fetch | $0.00075 per billable request | $0.75/1,000; count of returned results does not change the request price. Billing requires a successful result. Budget the paid rate rather than the current introductory free period, which ends at 00:00 Beijing time on 1 November 2026. [Retrieval billing](https://api-docs.deepseek.com/guides/search/). |
| Play subscription deductions | 15% assumption for the standard Play Billing route | Turkey/remaining-market subscriptions are listed at 15%; the current schedule also lists 10% service plus 5% Play billing for auto-renewing subscriptions in the named updated regions. Alternative-billing programs differ. Check enrollment/region before launch. [Service fees](https://support.google.com/googleplay/android-developer/answer/112622). |

Images are billed as input tokens, up to 1,024 tokens per image under the current
DeepSeek documentation. The phone may send a full image plus crop and may retry
the vision pass. The estimates below include text and image tokens together;
do not add image tokens again. [Vision billing](https://api-docs.deepseek.com/guides/vision/).

## Cost per user query: scenarios, not measured mobile averages

Sum tokens over **all** model calls in a turn. A query can require multiple
planning, tool and synthesis calls. Token rates apply to tokens, not questions.

| Assumption | Quick text check | Screenshot research | Deep comparison |
|---|---:|---:|---:|
| Mercury input / output tokens, aggregated | 8,000 / 800 | 25,000 / 1,500 | 80,000 / 3,500 |
| Vision input / output tokens, aggregated | 0 / 0 | 4,000 / 400 | 8,000 / 800 |
| Billable searches + fetches | 2 | 5 | 8 |
| Model charge | $0.00216 | $0.00605 | $0.01845 |
| Vision charge | $0 | $0.00168 | $0.00336 |
| Retrieval charge | $0.00150 | $0.00375 | $0.00600 |
| Direct API subtotal | **$0.00366** | **$0.01148** | **$0.02781** |
| Budget: API × 1.20 + $0.001 request infrastructure | **$0.005392** | **$0.014776** | **$0.034372** |

The 20% retry/failure allowance and $0.001 infrastructure figure are assumptions,
not provider fees or hosting quotes. Some failed retrievals are not charged;
model work, unsuccessful research and unknown billing can still cost money.
The heavy scenario is not a worst-case bound. Longer history, additional vision
output/retries and repeated tools can exceed it.

Formula:

```text
API = (Mercury input × 0.20 + Mercury output × 0.70
     + Flash input × 0.30 + Flash output × 1.20) / 1,000,000
     + (billable searches + fetches) × 0.00075
Planning service cost = API × 1.20 + 0.001
```

Repository context: the October 20 desktop screening reported roughly $0.00242
per attempt for one Mercury 2.5/DeepSeek profile and $0.04311 for a larger
multi-provider/verification profile. The Mercury 3 profile had incomplete cost
coverage. Those are small historical experiments, not a mobile cost estimate or
production-quality proof. See [the screening](../benchmarks/searchbench-2026-10-20.md)
and [its cost flags](../benchmarks/searchbench-2026-10-20.csv).

Before final prices, instrument 200–500 representative mobile turns: all model
usage (including vision), billable retrievals, retries, errors, latency, cache
status and whether the answer was actually useful. Reconcile the aggregate with
provider invoices. Report mean, median and p95 cost per attempted and accepted
answer. Today's optional Mercury token display does not supply that full ledger.

## Smaller-model routing and cache recalculation

Updated 31 October: use Ministral **3B and 8B**, with no 14B route. Current
official rates per million tokens are 3B $0.10 input / $0.10 output,
8B $0.15 / $0.15, and Mistral-hosted GLM 5.3 Flash $0.15 / $0.50
($0.03 cached input). Sources: [3B model card](https://docs.mistral.ai/models/ministral-3-3b-25-12),
[8B model card](https://docs.mistral.ai/models/ministral-3-8b-25-12),
[GLM Flash model card](https://docs.mistral.ai/models/zai-glm-5-3-flash).

A hypothetical compact 600-input / 200-output answer costs **$0.00008 on 3B**,
**$0.00012 on 8B**, or **$0.00019 on GLM Flash**, before retries and serving.
Those are token assumptions, not measured mobile averages. Mercury at its regular
$0.20/$0.70 rates costs $0.00026 for the identical prompt; promotional pricing
must be treated separately. Reducing prompt size and unnecessary retrievals can
matter more than the model swap itself.

Live synthetic checks using the configured Mistral key are recorded in
[the benchmark](../benchmarks/ministral-synthetic-2026-10-31.md). Small-model
arithmetic mistakes and Turkish wording errors prevent treating these as
general-purpose substitutes for research. Translation and Turkish rewriting
use 8B; 3B is limited to eligible English rewrites and approved basic definitions.
GLM Flash was compared but is not enabled as a production route here.

The implementation limits the cheap route to eligible independent static text
requests, with Mercury fallback. Shopping, fresh prices, merchant credibility,
screen context and conversation-dependent questions retain research. The answer
cache is local process memory, bounded to 32 entries and ten minutes, scoped to
the configured credential, exact question, language, style and model. This is
application answer reuse; it is separate from provider prompt caching. No price
or merchant-result cache savings are assumed.

Recalculation preserves the earlier research costs, assumes eligible simple
calls are 25% 3B / 75% 8B at 600/200 tokens, and keeps the remaining research
mix 75% screenshot / 25% deep. Each estimate includes the same 20% API allowance
and $0.001 per-request infrastructure assumption:

| Eligible simple share | Earlier quick-research budget for simple requests | Mercury with the same compact prompt, no simple-request retrievals | Routed, no answer-cache hits | Routed, 10% of simple requests cached |
|---|---:|---:|---:|---:|
| 20% | $0.016818 | $0.016002 | **$0.015966** | $0.015964 |
| 40% | $0.013962 | $0.012330 | **$0.012258** | $0.012253 |
| 60% | $0.011105 | $0.008657 | **$0.008549** | $0.008541 |

The first column of costs assumes each old simple task incurred the previous
quick-research workload including two retrievals. The old agent could already
answer without tools, so this comparison is an optimistic savings scenario.
The same-prompt Mercury column isolates the smaller-model benefit more fairly.
Cache-hit rates and eligible shares are hypotheses; the narrow route may have
very little traffic in a shopping app. Token-level prompt cache discounts are
not included. Reproduce with
`python kriko-mobile/tools/estimate-routing-cost.py`.

For the original shopping-heavy mix, the revised modeled average is about
**1.60 cents per query**, versus 1.68 cents previously. Keep the conservative
**2-cent credit budget** until representative mobile telemetry is available.
At full use, $6.99/100 credits leaves about **$3.69**, and $12.99/250 credits
about **$5.64**, after an assumed 15% Play deduction and $0.25/$0.40 other
variable costs. These are contribution estimates before fixed costs and taxes.
Do not expand research allowances based only on cheap text benchmarks; heavy
checks still need weighted credits and monitoring needs a separate budget.

Keep the initial **100 Plus / 250 Pro research credits**. A separate allowance
of, for example, 500 eligible simple answers has a modeled direct 3B/8B charge
of about $0.055, or $0.566 with the deliberately conservative per-request
infrastructure assumption and retry allowance. It must have its own cap and
count a fallback as research only with a clearly disclosed user-facing rule.
This is a package experiment, not an implemented billing entitlement.

## Packages to test

These are price experiments, not an estimate of willingness to pay. Use a
**check credit**: a standard research task is one credit; a deep task can be
three credits, disclosed before starting. That fits the modeled deep cost much
better than treating every query as identical. Keep rerunning research distinct
from reopening a saved answer. Do not bill user-visible credits for a failed
answer merely because internal provider spend occurred.

| Package | Example price | Allowance | Full-use contribution at $0.015/credit |
|---|---:|---:|---:|
| BYOK | Free | User supplies and pays provider keys | No hosted inference margin; keep direct API use outside the hosted allowance. |
| Kriko Plus | $6.99/month | 100 credits | **$4.19/month** after assumed Play fee and $0.25 other variable support/serving cost |
| Kriko Pro | $12.99/month | 250 credits | **$6.89/month** after assumed Play fee and $0.40 other variable cost |
| Extra checks | $2.99 one-time | 30 credits | **$1.99/pack** after assumed 15% deduction and $0.10 other variable cost; actual one-time-product fee eligibility must be checked |

For Plus, the arithmetic is `6.99 × 0.85 − 100 × 0.015 − 0.25 = 4.1915`.
That is contribution, **not net profit**. Excluded: VAT/sales tax, income tax,
refunds/chargebacks, customer acquisition, founder salaries and fixed overhead.
At $0.03/credit, full-use Plus contribution falls to about **$2.69**, and Pro to
**$3.14**. With hypothetical $500 monthly fixed overhead, Plus needs about 120
full-use subscribers to cover it at the base assumption, before those exclusions.

The strongest first offer may be Plus plus top-up packs, delaying Pro until
usage is measured. Shopping can be occasional: packs provide a purchase path
without asking everyone to justify a recurring subscription. Price history,
saved shortlists and useful recurring monitoring could improve retention, but
the current tracker is foreground-only and should not be sold as background
alerts. Avoid an annual discount until full-use costs and retention are known.

## Price monitoring can consume the margin

A daily watch is around 30 checks per 30-day month. At one paid fetch/check,
that is **$0.0225 per product/month** in retrieval alone, or $0.045 if each check
also needs one paid search. An hourly watch is 720 checks: **$0.54–$1.08 per
product/month** before model, hosting, retries and merchant-data costs. Ten
hourly watches can therefore cost $5.40–$10.80 in retrieval alone.

Include a small daily-watch allowance, charge separately for faster intervals,
and keep monitoring in a separate budget. Avoid an LLM for ordinary exact-price
extraction when a reliable structured price is available. Merchant blocks and
ambiguous prices must produce a failed observation rather than an invented price.

## Path to a profitable launch

1. Test the APK with real buyers, including the voice flow and power-button
   assistant. Measure completed decisions and trust, not only number of chats.
2. Build the hosted backend, entitlement verification, full cost ledger and
   spending caps. Separate the direct APK and Play update configurations.
3. Complete privacy/consent, reporting, deletion and review materials. Build and
   validate the production-signed AAB and native compatibility.
4. Run the required test track for this account/app. Choose initial countries
   and regional prices deliberately, then expand from observed demand.
5. Pilot one paid plan and top-ups. Watch conversion, repeated weekly use,
   refunds, churn, cost per accepted answer and contribution after acquisition.
   API margin alone does not establish a sustainable business.

Affiliate revenue can supplement this later, but recommendations and merchant
credibility must remain independent of commission. Any affiliate placement
should be clearly disclosed, with the disclosure and applicable market rules
reviewed before enabling it. No affiliate revenue is assumed in this model.
