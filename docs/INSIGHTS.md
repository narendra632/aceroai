# How to read the Insights page

Acero watches itself. Every call it makes to a model — including the ones you never see —
records what it cost, how long it took, and whether it worked. This page is that record.

It is **read-only**. Nothing on it changes anything, so it is safe to open, reload, and
leave open.

---

## The four numbers at the top

### Estimated spend

**It says "estimated" because it is.** Acero prices each call itself, from a price list
kept in the code, using the token counts the provider reported. It has no access to your
actual OpenAI or Google bill. So this is a close, honest reckoning — not an invoice.

Two consequences worth knowing:

- **A price is frozen when the call happens.** Each row records which version of the price
  list produced it. If a provider changes prices tomorrow, last month's spend stays what it
  was. It does not silently rewrite itself.
- **An unknown model costs "nothing known", not zero.** If you use a model that isn't in
  the price list, the call is counted as **unpriced** rather than free. A zero would quietly
  understate your total; a visible gap gets noticed and fixed.

### Typical reply

The **median** — half your replies are faster, half slower. Beneath it, "first word
after…" is the moment text starts appearing, which is what actually feels like the wait.

Both figures count **only successful chat replies.** Background work is excluded because
nobody waits on it, and failures are excluded because they abort in milliseconds — leaving
them in would drag the median down and report a speed you never experience.

### Slowest 5%

Also called p95: **out of every twenty replies, one is at least this slow.**

This is here instead of an average, and the difference matters. Take five replies —
100 ms, 110 ms, 120 ms, 130 ms, and one bad 30-second one. The average is **6 seconds**,
which describes nothing that happened: no reply took anywhere near that. The median says
120 ms, and p95 says the bad one exists. Together they tell you both the normal case and
the worst case; an average hides both.

### Failures

How many calls did not complete. The **What goes wrong** panel breaks them down by kind,
and that breakdown is the point: a rate limit and a billing problem return the same error
code from most providers, but one means *wait* and the other means *go fix your account*.

---

## "X% of this spend is work you never see"

A message is not one model call. Sending "remind me to call the bank" typically costs
**four**:

1. an embedding of your message, to search Acero's memory
2. the reply itself
3. a second model call afterwards, deciding whether anything durable was worth remembering
4. an embedding of anything it decided to store

Only the second one produces text on your screen. The other three used to be invisible —
billed, and counted nowhere. They're small in money (a few percent) and large in count
(about a third of all calls), and now they're on the chart alongside everything else.

The **Spend over time** chart splits by exactly this: *Replies*, *Recall*, *Learning*.

---

## Where the money goes

Spend per model, largest first. The **fixed** tag marks the embedding model, which is not
selectable: every memory Acero has was written by it, and a different model would write
those numbers in its own coordinate system, so old memories would become unreadable rather
than merely different.

---

## The waterfall

Click any call under **Recent calls** to see it broken into stages: saving your message,
recalling what it knows, assembling the prompt, each round with the model, each tool it
ran. The longest stage is marked, because that is the answer to "why was this one slow".

This view is why the whole feature exists. It once made a 12-second embedding stall
obvious — but only by reading raw logs live, at the moment it happened. Now it's a click,
for any call, afterwards.

One row is drawn apart from the others: **first word appears**. Every other stage is a
*duration*; that one is a *moment*, measured from the start. Drawing it as a bar beside the
rest would double-count time and make the total look wrong.

Underneath, when memory contributed anything, you also get **which facts it used** for that
call. Not a count — the facts themselves. It is the same list the third control under a
reply shows, except that one can only explain the conversation still open in front of you,
and this one explains any call ever recorded.

If a call shows no facts, that is an answer rather than a gap. Asking Acero to write some
code has nothing to do with anything it knows about you, and it now recalls nothing at all
on those turns instead of padding the prompt.

---

## How far back it goes

Detail is kept for a while; totals are kept forever.

| | Kept |
|---|---|
| Per-stage waterfalls | 30 days |
| Individual calls | 400 days |
| Daily spend totals | forever |

So **your spend history never disappears** — but for a period far enough back, you can see
what you spent without being able to open one call and inspect it.

Two things genuinely end with the detail: **latency percentiles** and **error kinds**. A
median cannot be rebuilt from daily medians. Rather than invent a number for an old period,
those panels go blank.

Windows are set with `SPAN_RETENTION_DAYS` and `TURN_RETENTION_DAYS` — see
[`DEPLOY.md`](DEPLOY.md).

---

## The spend limit

Set a monthly ceiling in **Settings → Spend limit**, and Acero stops replying once this
month's estimated spend passes it. Nothing is capped until you set one.

Three things worth knowing about how it behaves:

- **Everything counts** — replies, recall, and learning — because that is what the
  provider bills you for. A limit that only counted visible replies would let a third of
  the calls slip past it.
- **It is checked before each message, not enforced mid-reply.** A reply already in
  progress finishes, so the total can pass the limit by one message. Stopping a reply
  halfway to save a fraction of a cent would be the worse product.
- **You are warned at 80%**, not only when you are stopped. A slim line appears above the
  message box, and the Settings bar changes colour.

When you are stopped, the message box is replaced by an explanation and a **Change limit**
button. Raising the limit takes effect immediately — no restart, no waiting. The allowance
resets on the 1st of the month, in your timezone.

## What this page deliberately does not do

- **No alerts.** Nothing here will notify you about a spike. You have to look.
- **No sampling.** Every call is recorded, which is affordable at one user and would not be
  at scale.
- **No external exporter.** Traces are shaped after OpenTelemetry's naming so that sending
  them somewhere later is a formatting change rather than a redesign — but nothing is sent
  anywhere today.
