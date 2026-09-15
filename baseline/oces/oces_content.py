"""
Authored OCES variant content (Task 4, Phase 4). Owner: Lamei. AI-DRAFTED candidates.

This module holds the AI-drafted text for the additional evaluation (OCES). For every seed
there is exactly one PARAPHRASE and one NEUTRAL-DISTRACTOR variant. build_oces.py selects
the seeds deterministically from the committed baselines, derives the sanitation-invariant
"clean request" for each seed, joins the seeds with the entries here (by seed baseline_id +
family), runs the mechanical checks, and freezes the JSON. This module is the single place
the actual English lives, so review is easy.

PARAPHRASE entries carry the FULL variant text (a free reword; that is their purpose).
DISTRACTOR entries carry ONLY the neutral clause to append. The builder composes the
distractor as:  <exact OCES clean request> + " " + <neutral clause>.  So a distractor never
rewrites the request's casing/punctuation/tokenization -- it only ADDS one unrelated,
affect-free sentence. That keeps the causal story clean: clean request -> same exact request
+ neutral distractor.

Honesty / discipline (docs/stage3/tasks/task_4_lamei.md, CONTRACTS 6.6):
  * These candidates are AI-DRAFTED and NOT yet human-reviewed. `tier` here is a PROPOSED
    tier, not a claim of human review; `reviewer` is left empty in the frozen output and the
    per-variant `author` is recorded honestly as an AI draft.
  * OCES is an additional evaluation authored AFTER the evaluated defenses were frozen, by
    authors aware of the defenses. It is NOT a blind holdout and NOT design-independent.
  * Oracle is label-invariance vs the seed baseline (oces.paraphrase / oces.distractor,
    relation=invariant). No negation, no directional oracle, no confidence-drop rule.
  * Every variant is ordinary, valid English in clean orthography, so a measured change is
    attributable to SEMANTICS, not sanitation. build_oces.py asserts clean_text is a no-op on
    every clean request AND every variant, and that both are within both tokenizers' limits.

Transformation subtypes (descriptive only; NOT new contract families):
  paraphrase : lexical | syntactic | compression | expansion | clause_restructuring
  distractor : mundane_factual | administrative | logistical | temporal | ordinary_observation

`risk` is one of low|medium|high (semantic_risk). Emotion is a 7-way task, so subtle shifts
are riskier there than in binary sentiment; noisy/garbled or very short seeds are flagged
higher and proposed REVIEW so a human keeps them visible rather than auto-scoring them.
"""

# PARAPHRASE: (seed_baseline_id, "paraphrase", subtype, FULL_variant_text, risk, tier, rationale)
# DISTRACTOR: (seed_baseline_id, "distractor", subtype, NEUTRAL_CLAUSE,     risk, tier, rationale)

_DISTRACTOR_RATIONALE = (
    "Clean request used verbatim as the prefix; one unrelated, affect-free {subtype} clause "
    "appended, with no casing/punctuation rewrite; affective content untouched."
)


def _d(subtype: str) -> str:
    return _DISTRACTOR_RATIONALE.format(subtype=subtype)


EMOTION_VARIANTS = [
    # --- anger ---
    ("dataset-anger-0", "paraphrase", "lexical",
     "I didn't think I was angry, but now, as I type and watch my words vanish into cyberspace, I'm really furious that this is happening.",
     "medium", "REVIEW",
     "Lexical swaps (pissed->furious, evaporate->vanish); anger preserved but intensity wording changed, so kept visible for review."),
    ("dataset-anger-0", "distractor", "logistical",
     "The document was last saved at 4:15 pm.",
     "low", "SILVER", _d("logistical")),

    ("dataset-anger-1", "paraphrase", "syntactic",
     "Every moment feels like torture, and there is nowhere I can escape to or return to the life I once knew.",
     "medium", "REVIEW",
     "Syntactic recast of a strong-affect sentence; meaning preserved but re-review for intensity."),
    ("dataset-anger-1", "distractor", "ordinary_observation",
     "The building has four floors and two staircases.",
     "low", "SILVER", _d("ordinary_observation")),

    ("dataset-anger-2", "paraphrase", "lexical",
     "I never kissed a guy because every time I tried, I would panic and feel disgusted.",
     "high", "REVIEW",
     "Dataset label 'anger' is noisy here (reads fear/disgust); 7-way prediction is unstable, so flagged high and kept for review."),
    ("dataset-anger-2", "distractor", "temporal",
     "The cafe across the street opens at eight each morning.",
     "high", "REVIEW",
     "Noisy underlying label; the seed's emotion is ambiguous, so kept visible even though only a neutral clause is appended."),

    # --- disgust (handwritten, clean) ---
    ("handwritten-disgust-0", "paraphrase", "syntactic",
     "The milk had turned lumpy and curdled, and its stench made me gag.",
     "low", "SILVER",
     "Clear disgust cue (curdled/stench/gag) preserved with lexical/syntactic variation."),
    ("handwritten-disgust-0", "distractor", "mundane_factual",
     "The hallway has three ceiling lights.",
     "low", "SILVER", _d("mundane_factual")),

    ("handwritten-disgust-1", "paraphrase", "syntactic",
     "Maggots were crawling through the rotting meat inside the bin.",
     "low", "SILVER",
     "Strong disgust imagery preserved; minor reordering only."),
    ("handwritten-disgust-1", "distractor", "logistical",
     "The office printer is beside the window.",
     "low", "SILVER", _d("logistical")),

    ("handwritten-disgust-2", "paraphrase", "clause_restructuring",
     "Revolted by the taste, he spat out the mouldy bread.",
     "low", "SILVER",
     "Clause order swapped; disgust cue (revolted/mouldy) preserved."),
    ("handwritten-disgust-2", "distractor", "logistical",
     "The bus stop is two blocks from the building.",
     "low", "SILVER", _d("logistical")),

    # --- fear ---
    ("dataset-fear-0", "paraphrase", "syntactic",
     "It frightens me that I own it.",
     "medium", "REVIEW",
     "Very short, semantically thin seed; a 7-way model may be unstable, so kept for review."),
    ("dataset-fear-0", "distractor", "administrative",
     "The receipt is filed in the top drawer.",
     "medium", "REVIEW",
     "Short/ambiguous seed; kept visible for review even though only a neutral clause is appended."),

    ("dataset-fear-1", "paraphrase", "lexical",
     "I feel like someone's odd uncle at a party, trying to break the ice by showing off an amazing talent, expecting the guests to be impressed, but instead making everything a hundred times more awkward.",
     "medium", "REVIEW",
     "Longer social-anxiety seed; meaning preserved, but fear-vs-embarrassment is subtle for a 7-way head."),
    ("dataset-fear-1", "distractor", "temporal",
     "The party was held on the second Saturday of the month.",
     "low", "SILVER", _d("temporal")),

    ("dataset-fear-2", "paraphrase", "clause_restructuring",
     "A year ago yesterday, I remember feeling so uncertain, so scared of what our future held.",
     "low", "SILVER",
     "Explicit fear cue (scared) preserved; clause reordered."),
    ("dataset-fear-2", "distractor", "ordinary_observation",
     "The calendar on the wall still showed last month.",
     "low", "SILVER", _d("ordinary_observation")),

    # --- joy (dataset labels are noisy here) ---
    ("dataset-joy-0", "paraphrase", "lexical",
     "I strongly feel that, at this point in my life, I no longer want to walk the path I'm on, and honestly, I have no idea where my life is heading from here.",
     "high", "REVIEW",
     "Dataset label 'joy' is noisy (text reads uncertain/low); 7-way prediction unstable, flagged high."),
    ("dataset-joy-0", "distractor", "logistical",
     "The bus schedule changes at the end of the season.",
     "high", "REVIEW",
     "Noisy underlying label; kept visible for review even though only a neutral clause is appended."),

    ("dataset-joy-1", "paraphrase", "lexical",
     "I read a lot about discovery and exploration in the wild west, and while I find those ideas precious and often take part in them myself, this book simply brings a refined feeling when I sit back in the chair for some quiet time.",
     "medium", "REVIEW",
     "Contentment/joy is mild and diffuse; meaning preserved but re-review for label stability."),
    ("dataset-joy-1", "distractor", "ordinary_observation",
     "The chair is placed beside the north window.",
     "low", "SILVER", _d("ordinary_observation")),

    ("dataset-joy-2", "paraphrase", "compression",
     "I love feeling valuable, I love making the choice, and I love that it's easy to choose to feel good.",
     "low", "SILVER",
     "Clear repeated joy cue (love/feel good) preserved; lightly compressed."),
    ("dataset-joy-2", "distractor", "mundane_factual",
     "The notebook where I write this has a plain grey cover.",
     "low", "SILVER", _d("mundane_factual")),

    # --- neutral (handwritten, clean) ---
    ("handwritten-neutral-0", "paraphrase", "compression",
     "The train leaves platform four at nine a.m.",
     "low", "SILVER",
     "Neutral factual statement; compressed, no affect introduced."),
    ("handwritten-neutral-0", "distractor", "mundane_factual",
     "A new coat of paint was applied to the railings last week.",
     "low", "SILVER", _d("mundane_factual")),

    ("handwritten-neutral-1", "paraphrase", "lexical",
     "The report has to be submitted by the end of the month.",
     "low", "SILVER",
     "Neutral administrative statement; lexical variation only."),
    ("handwritten-neutral-1", "distractor", "administrative",
     "The office has three meeting rooms on this floor.",
     "low", "SILVER", _d("administrative")),

    ("handwritten-neutral-2", "paraphrase", "lexical",
     "She set the folder down on the desk and switched the computer on.",
     "low", "SILVER",
     "Neutral action description; lexical variation only."),
    ("handwritten-neutral-2", "distractor", "ordinary_observation",
     "The desk faces a window overlooking the car park.",
     "low", "SILVER", _d("ordinary_observation")),

    # --- sadness ---
    ("dataset-sadness-0", "paraphrase", "lexical",
     "I feel as though the rest of my year will be jaded because of my love for this first one.",
     "medium", "REVIEW",
     "Slightly garbled seed; meaning approximated, so flagged for review."),
    ("dataset-sadness-0", "distractor", "ordinary_observation",
     "The wall calendar lists twelve months on a single page.",
     "medium", "REVIEW",
     "Garbled seed; kept visible even though only a neutral clause is appended."),

    ("dataset-sadness-1", "paraphrase", "syntactic",
     "I'm feeling quite weepy; can you get rid of them? And she did.",
     "medium", "REVIEW",
     "Weepy cue preserved; disjointed narration makes label less certain, so review."),
    ("dataset-sadness-1", "distractor", "mundane_factual",
     "The meeting room has six chairs.",
     "medium", "REVIEW",
     "Disjointed seed; kept visible even though only a neutral clause is appended."),

    ("dataset-sadness-2", "paraphrase", "lexical",
     "I walked away from the weekend feeling simply dirty, as if I had done something truly harmful, and more than anything, that feeling overpowers my feeble attempts to justify what I did last weekend.",
     "medium", "REVIEW",
     "Guilt/sadness preserved; long emotional sentence, re-review for shift."),
    ("dataset-sadness-2", "distractor", "temporal",
     "The lecture starts at ten and ends at noon.",
     "low", "SILVER", _d("temporal")),

    # --- surprise (short / noisy) ---
    ("dataset-surprise-0", "paraphrase", "lexical",
     "I'm feeling really strange.",
     "high", "REVIEW",
     "Very short/ambiguous ('weird'->'strange'); could read surprise, fear or neutral, so high risk."),
    ("dataset-surprise-0", "distractor", "temporal",
     "The clock on the wall reads half past three.",
     "high", "REVIEW",
     "Short/ambiguous seed; kept visible even though only a neutral clause is appended."),

    ("dataset-surprise-1", "paraphrase", "syntactic",
     "I was overwhelmed by how impressed I felt; I think these kids, they're years younger than me, I can call them kids, right?",
     "medium", "REVIEW",
     "Amazement/surprise cue preserved; conversational aside makes it less clean, review."),
    ("dataset-surprise-1", "distractor", "logistical",
     "The workshop lasted about two hours.",
     "low", "SILVER", _d("logistical")),

    ("dataset-surprise-2", "paraphrase", "clause_restructuring",
     "Beside me, I see smiling, and I feel very funny.",
     "high", "REVIEW",
     "Seed is near-nonsense (dataset noise); any paraphrase is approximate, so high risk and review."),
    ("dataset-surprise-2", "distractor", "ordinary_observation",
     "The room has two windows and a single door.",
     "high", "REVIEW",
     "Garbled seed; kept visible even though only a neutral clause is appended."),
]

SENTIMENT_VARIANTS = [
    # --- NEGATIVE ---
    ("sst2-val-18", "paraphrase", "expansion",
     "In the end, the movie is nothing but a plain old monster.",
     "medium", "REVIEW",
     "Cryptic seed with leading ellipsis; meaning approximated, so review."),
    ("sst2-val-18", "distractor", "logistical",
     "It runs for about ninety minutes.",
     "medium", "REVIEW",
     "Cryptic seed; kept visible even though only a neutral clause is appended."),

    ("sst2-val-35", "paraphrase", "lexical",
     "A string of ridiculous shoot-'em-up scenes.",
     "low", "SILVER",
     "Negative cue ('ridiculous') preserved; lexical variation."),
    ("sst2-val-35", "distractor", "mundane_factual",
     "The film was shot in two countries.",
     "low", "SILVER", _d("mundane_factual")),

    ("sst2-val-59", "paraphrase", "lexical",
     "It's just disappointingly superficial - a film with all the ingredients to be a fascinating, involving character study, yet it never does more than scratch the surface.",
     "low", "SILVER",
     "Clear negative judgement ('disappointingly superficial') preserved."),
    ("sst2-val-59", "distractor", "temporal",
     "The screening began at seven o'clock.",
     "low", "SILVER", _d("temporal")),

    ("sst2-val-110", "paraphrase", "lexical",
     "It earns no points for originality, wit, or intelligence.",
     "low", "SILVER",
     "Strong negative ('no points') preserved."),
    ("sst2-val-110", "distractor", "ordinary_observation",
     "The poster uses three colours.",
     "low", "SILVER", _d("ordinary_observation")),

    ("sst2-val-111", "paraphrase", "syntactic",
     "There isn't nearly enough fun here, even with some appealing ingredients present.",
     "low", "SILVER",
     "Negative ('not enough fun') preserved despite the concessive clause."),
    ("sst2-val-111", "distractor", "administrative",
     "The cinema has assigned seating.",
     "low", "SILVER", _d("administrative")),

    ("sst2-val-121", "paraphrase", "lexical",
     "It seems to me the film is about the art of ripping people off without ever letting them consciously realise you've done it.",
     "medium", "REVIEW",
     "Sentiment is implicit (descriptive sentence); negativity is inferential, so review."),
    ("sst2-val-121", "distractor", "logistical",
     "The plot unfolds across two cities.",
     "medium", "REVIEW",
     "Implicit-sentiment seed; kept visible even though only a neutral clause is appended."),

    ("sst2-val-136", "paraphrase", "lexical",
     "It looks and feels like a project that would work better on the small screen.",
     "low", "SILVER",
     "Faint-praise negative ('better suited for TV') preserved."),
    ("sst2-val-136", "distractor", "mundane_factual",
     "The runtime is listed as one hundred minutes.",
     "low", "SILVER", _d("mundane_factual")),

    ("sst2-val-162", "paraphrase", "lexical",
     "There seems to be no clear sense of where the story is going, or how long it will take to get there.",
     "low", "SILVER",
     "Negative ('no clear path') preserved."),
    ("sst2-val-162", "distractor", "ordinary_observation",
     "The film is divided into three acts.",
     "low", "SILVER", _d("ordinary_observation")),

    ("sst2-val-211", "paraphrase", "syntactic",
     "Saying this was done better in Wilder's Some Like It Hot is like saying the sun rises in the east.",
     "medium", "REVIEW",
     "Sarcastic comparison; sentiment depends on reading the idiom, so review."),
    ("sst2-val-211", "distractor", "temporal",
     "The earlier film was released decades ago.",
     "medium", "REVIEW",
     "Idiomatic/sarcastic seed; kept visible even though only a neutral clause is appended."),

    ("sst2-val-319", "paraphrase", "lexical",
     "Too much of it comes across as unfocused and underdeveloped.",
     "low", "SILVER",
     "Clear negative ('unfocused and underdeveloped') preserved."),
    ("sst2-val-319", "distractor", "mundane_factual",
     "The director also wrote the screenplay.",
     "low", "SILVER", _d("mundane_factual")),

    # --- POSITIVE ---
    ("sst2-val-13", "paraphrase", "lexical",
     "We root for Clara and Paul, and even like them, though perhaps the feeling is closer to pity.",
     "high", "REVIEW",
     "Mixed sentiment ('closer to pity'); the positive label is fragile, so high risk and review."),
    ("sst2-val-13", "distractor", "temporal",
     "The story is set over a single summer.",
     "high", "REVIEW",
     "Mixed-sentiment seed; kept visible even though only a neutral clause is appended."),

    ("sst2-val-17", "paraphrase", "lexical",
     "Audrey Tautou has a knack for choosing roles that magnify her outrageous charm, and in this literate French comedy she's as morning-glory exuberant as she was in Amelie.",
     "low", "SILVER",
     "Strong positive ('outrageous charm', 'exuberant') preserved."),
    ("sst2-val-17", "distractor", "mundane_factual",
     "The comedy is spoken in French.",
     "low", "SILVER", _d("mundane_factual")),

    ("sst2-val-52", "paraphrase", "syntactic",
     "Mr. Tsai is a highly original artist in his medium, and so is What Time Is It There?",
     "medium", "REVIEW",
     "Positive ('very original') preserved, but the film-title clause is awkward, so review."),
    ("sst2-val-52", "distractor", "logistical",
     "The film had its premiere at a festival.",
     "medium", "REVIEW",
     "Title-as-clause seed; kept visible even though only a neutral clause is appended."),

    ("sst2-val-109", "paraphrase", "lexical",
     "It's wonderful escapist fun that recreates a place and time that will never come again.",
     "low", "SILVER",
     "Positive ('great escapist fun') preserved."),
    ("sst2-val-109", "distractor", "mundane_factual",
     "The soundtrack features a dozen songs.",
     "low", "SILVER", _d("mundane_factual")),

    ("sst2-val-120", "paraphrase", "compression",
     "Warm Water Under a Red Bridge is a quirky, poignant Japanese film exploring the fascinating connections between women, water, nature, and sexuality.",
     "low", "SILVER",
     "Positive ('quirky and poignant', 'fascinating') preserved; lightly compressed."),
    ("sst2-val-120", "distractor", "logistical",
     "The film is roughly two hours long.",
     "low", "SILVER", _d("logistical")),

    ("sst2-val-201", "paraphrase", "clause_restructuring",
     "Within the film's conflict-powered plot there's a decent moral trying to get out, but it isn't that - it's the tension that keeps you in your seat.",
     "medium", "REVIEW",
     "Positive resolves late ('tension keeps you in your seat'); structure is tricky, so review."),
    ("sst2-val-201", "distractor", "administrative",
     "The film is rated for general audiences.",
     "low", "SILVER", _d("administrative")),

    ("sst2-val-227", "paraphrase", "lexical",
     "As the two leads, Lathan and Diggs are charming and share chemistry both as friends and as lovers.",
     "low", "SILVER",
     "Positive ('charming', 'chemistry') preserved."),
    ("sst2-val-227", "distractor", "ordinary_observation",
     "The pair appear in most of the film's scenes.",
     "low", "SILVER", _d("ordinary_observation")),

    ("sst2-val-248", "paraphrase", "lexical",
     "A complete world has been presented onscreen, rather than a series of carefully structured plot points building to a pat resolution.",
     "medium", "REVIEW",
     "Positive is comparative/implicit ('a full world, not... pat resolution'), so review."),
    ("sst2-val-248", "distractor", "logistical",
     "The film uses several outdoor locations.",
     "low", "SILVER", _d("logistical")),

    ("sst2-val-290", "paraphrase", "lexical",
     "Deliriously funny, fast and loose, easy for newcomers to enjoy, and full of surprises.",
     "low", "SILVER",
     "Strongly positive list ('deliriously funny', 'full of surprises') preserved."),
    ("sst2-val-290", "distractor", "temporal",
     "The screening lasted a little under two hours.",
     "low", "SILVER", _d("temporal")),

    ("sst2-val-341", "paraphrase", "clause_restructuring",
     "Anyone with even a passing interest in the events shaping the world beyond their own horizons deserves to see it.",
     "low", "SILVER",
     "Positive recommendation ('deserves to be seen') preserved; clause reordered."),
    ("sst2-val-341", "distractor", "mundane_factual",
     "The documentary includes archival footage.",
     "low", "SILVER", _d("mundane_factual")),
]
