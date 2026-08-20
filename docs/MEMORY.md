# How Acero remembers

Written for the person using the app, not the person maintaining it. If you want the
implementation, that is [`ARCHITECTURE.md`](ARCHITECTURE.md).

---

## The short version

Acero keeps a set of short sentences about you — "Narendra works at TCS", "Narendra goes
to the gym on weekday mornings". They live on the **Knowledge** page, where you can read,
edit, confirm and forget any of them.

Two things put facts there:

- **You ask.** "Remember that I have the AI-901 certification." It stores it there and
  then, and tells you it did.
- **It notices.** After every reply, a cheap model reads the exchange and asks "was
  anything durable said here?". This happens in the background, after you have your
  answer, so it never slows anything down.

Then, on every message you send, it looks for the facts that are actually about *that*
message and puts only those in front of the model.

---

## What it keeps, and what it does not

The rule is simple: **stable things about you, not the events of one afternoon.**

| Kept | Not kept |
|---|---|
| You work at TCS | You are running ten minutes late |
| You prefer tea in the evening | You had tea at 4pm on Tuesday |
| You have two sisters | You called your sister yesterday |
| You are taking the AI-103 exam | The exam page was slow to load |

One-off logistics belong in **tasks** and **journal entries**, which are separate and
searchable in their own right. Memory is for the things that would still be true in six
months.

---

## It no longer throws things away

This is the part worth knowing, because it used to get it wrong.

Acero compares a new fact against everything it already holds, using *meaning* rather than
words. If the new one looked too close to an old one, it used to assume you were repeating
yourself and **silently delete it**.

That went badly. Measured on two real facts:

```
"Narendra has completed the AI-901 certification."
"Narendra has completed the AI-103 certification."     0.098 apart  ← treated as the same
```

Two different certifications, three characters apart, and the second one vanished. Worse,
the same measure got the opposite case wrong too:

```
"The user has sisters."
"Narendra has sisters."                                0.216 apart  ← treated as different
```

The identical fact, kept twice. So the setting was wrong in both directions at once, which
means no amount of adjusting it would have fixed anything. Closeness in meaning tells you
two sentences are *about the same subject*. It cannot tell you they *say the same thing*.

**So it stopped deciding.** A new fact that resembles an old one is now stored anyway and
marked *"may repeat another"* on the Knowledge page. Open it and you see both, with two
buttons: **Not a duplicate** (they are genuinely different — the flag goes away) or
**Forget this one**. You decide, not a threshold.

Deleting is the move that cannot be undone by noticing later, so it is the one that has to
be earned.

---

## How it picks what to recall

Every message you send gets two searches, not one, and they are good at opposite things.

**The meaning search** understands that "where do I work" and "Narendra works at TCS" are
the same topic even with no words in common. What it cannot do is tell you *how* related
something is. Every fact about one person scores in a narrow range, so it will happily
report that "Narendra has two sisters" is nearly as relevant to your job question as your
job is. On its own it returned a fixed twelve facts for every message — including "write a
python function to reverse a list", which had you sitting there with your family and gym
schedule attached to a coding question.

**The word search** is the opposite: exact where the other is vague. Ask about
"certifications" and it finds the certification facts and nothing else. Ask "where do I
work" and it finds nothing, because your job fact says *works*, not *where*. (It does
handle *works* / *working* / *work* — it reduces words to their stem. It just cannot leap
between different words for the same idea.)

Neither is good enough alone. Both fail, but they fail in **opposite directions**, so
Acero runs both and trusts what they agree on:

- Found by **both** searches → kept. This is the strong signal.
- Found by the **meaning search only** → kept only if it is genuinely close, and at most
  four of them.
- Found by the **word search only** → kept only if the matching word is *rare* in your
  memory, and at most three. "Dentist" identifies a fact; "prefers" does not.

The result is that the limit stopped being a target. Measured against real memory:

| you ask | facts sent before | after |
|---|---|---|
| "remind me about my exam" | 12 | **7**, with all three exam facts first |
| "where do I work" | 12 | **8**, with your job first |
| "hello" | 12 | **4** |
| "write a python function to reverse a list" | 12 | **0** |

---

## You can see exactly what it used

Under every reply there is a third icon beside copy and regenerate. Tap it and you get the
facts that were sent to the model for that message — the real list, not a summary of it —
along with which search found each one.

When nothing was recalled, **the icon is not there at all**. That is deliberate: after the
change above, recalling nothing is a normal, common outcome, and a button that opens onto
"none" would be noise on exactly the turns that need no explaining.

The same list appears on the **Insights** page under any past call, so you can go back to
a conversation from last month and still ask "what did it know when it said that?".

This exists because of a real failure. Acero once said it had stored something it had not,
and there was no way to notice for three exchanges. A claim you can check beats a claim you
cannot.

---

## Changing your mind

- **Correct it in chat** — "actually I moved to TCS". Acero replaces the old fact and
  *says so* in its reply. The old version is not deleted; it is kept as history, visible
  under the fact on the Knowledge page.
- **Forget it in chat** — "forget that I prefer tea". It will name what it forgot rather
  than just agreeing, so you can check it did the right one.
- **Edit it yourself** on the Knowledge page. Editing supersedes rather than overwrites,
  so you can always see what it used to think.
- **Confirm it** to promote a guess to something you have stated. Everything Acero infers
  is, after all, an inference.

Forgetting is reversible — the fact stops reaching the model immediately, and Undo brings
it back. The background extractor is deliberately **not** allowed to delete anything; only
you, or Acero acting on something you explicitly said, can do that.

---

## The honest limits

- **A stray word can still pull in a fact.** "Write a python function" shares a stem with
  "Narendra *writes* his own summaries", so that one can turn up. At most three such facts,
  and they are never presented as the strong signal.
- **A very long message recalls less well.** Both searches blur when you send three
  paragraphs covering five subjects — the meaning search averages them into one point, and
  the word search gets diffuse. Short, specific questions get the best of this.
- **It does not go back and tidy up.** Conflicts and duplicates already sitting in your
  memory from before this change are still there. A "Review conflicts" action is on the
  roadmap; this change fixed how new facts arrive, not the backlog.
- **It cannot correct a fact it did not recall.** Correcting works on the facts in front of
  it for that message. Naming the thing you want changed is usually enough to surface it.
