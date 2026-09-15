"""
Authored OCES variant content (Task 4, Phase 4). Owner: Lamei.

This module holds the hand-authored text for the additional evaluation (OCES). For every
seed there is exactly one PARAPHRASE and one NEUTRAL-DISTRACTOR variant. build_oces.py
selects the seeds deterministically from the committed baselines, joins them with the
entries here (by seed baseline_id + family), runs the mechanical checks, and freezes the
JSON. This module is the single place the actual English lives, so review is easy.

Honesty / discipline (see docs/stage3/tasks/task_4_lamei.md):
  * These candidates are AI-DRAFTED and NOT yet human-reviewed. `tier` here is a PROPOSED
    tier, not a claim of human review; `reviewer` is left empty in the frozen output.
  * OCES is an additional evaluation AUTHORED AFTER the defenses were frozen, by authors who
    knew the defenses. It is NOT a blind or design-independent holdout.
  * The oracle is label-invariance vs the seed baseline (oces.paraphrase / oces.distractor,
    relation=invariant). No negation, no directional oracle, no confidence-drop rule.
  * Every variant is ordinary, valid English rendered in clean orthography (single spaces,
    no control/format characters, comfortably under the token limit), so a measured change
    is attributable to SEMANTICS, not to sanitation. build_oces.py asserts clean_text is a
    no-op on every variant.

Transformation subtypes (descriptive only; NOT new contract families):
  paraphrase : lexical | syntactic | compression | expansion | clause_restructuring
  distractor : mundane_factual | administrative | logistical | temporal | ordinary_observation
    (a distractor keeps the seed's wording, in clean orthography, and appends ONE neutral,
     non-affective clause; the affective content is untouched.)

`risk` is one of low|medium|high (semantic_risk). Emotion is a 7-way task, so subtle shifts
are riskier there than in binary sentiment; noisy/garbled or very short seeds are flagged
higher and proposed REVIEW so a human keeps them visible rather than auto-scoring them.
"""

# Each entry: (seed_baseline_id, family, subtype, variant_text, risk, proposed_tier, rationale)
# family is "paraphrase" or "distractor" (expanded to oces.paraphrase / oces.distractor).

EMOTION_VARIANTS = [
    # --- anger ---
    ("dataset-anger-0", "paraphrase", "lexical",
     "I didn't think I was angry, but now, as I type and watch my words vanish into cyberspace, I'm really furious that this is happening.",
     "medium", "REVIEW",
     "Lexical swaps (pissed->furious, evaporate->vanish); anger preserved but intensity wording changed, so kept visible for review."),
    ("dataset-anger-0", "distractor", "logistical",
     "I didn't think I was angry, but now that I am typing away, feeling my words evaporate into cyberspace, I am very pissed that this is happening. The document was last saved at 4:15 pm.",
     "low", "SILVER",
     "Wording preserved; one neutral logistical clause appended; affective content untouched."),

    ("dataset-anger-1", "paraphrase", "syntactic",
     "Every moment feels like torture, and there is nowhere I can escape to or return to the life I once knew.",
     "medium", "REVIEW",
     "Syntactic recast of a strong-affect sentence; meaning preserved but re-review for intensity."),
    ("dataset-anger-1", "distractor", "ordinary_observation",
     "I feel tortured every moment, and there is nowhere I can go to get away from it or to get back to what I was used to. The building has four floors and two staircases.",
     "low", "SILVER",
     "Wording preserved; one neutral ordinary-observation clause appended."),

    ("dataset-anger-2", "paraphrase", "lexical",
     "I never kissed a guy because every time I tried, I would panic and feel disgusted.",
     "high", "REVIEW",
     "Dataset label 'anger' is noisy here (reads fear/disgust); 7-way prediction is unstable, so flagged high and kept for review."),
    ("dataset-anger-2", "distractor", "temporal",
     "I never kissed a guy, because every time I tried, I would freak out and feel disgusted. The cafe across the street opens at eight each morning.",
     "high", "REVIEW",
     "Noisy underlying label; even with wording preserved the seed's emotion is ambiguous, so kept visible."),

    # --- disgust (handwritten, clean) ---
    ("handwritten-disgust-0", "paraphrase", "syntactic",
     "The milk had turned lumpy and curdled, and its stench made me gag.",
     "low", "SILVER",
     "Clear disgust cue (curdled/stench/gag) preserved with lexical/syntactic variation."),
    ("handwritten-disgust-0", "distractor", "mundane_factual",
     "The milk had curdled into lumps and the smell made me gag. The carton listed a best-before date of the twelfth.",
     "low", "SILVER",
     "Wording preserved; neutral factual clause appended."),

    ("handwritten-disgust-1", "paraphrase", "syntactic",
     "Maggots were crawling through the rotting meat inside the bin.",
     "low", "SILVER",
     "Strong disgust imagery preserved; minor reordering only."),
    ("handwritten-disgust-1", "distractor", "logistical",
     "There were maggots crawling through the rotting meat in the bin. Rubbish collection happens on Wednesdays.",
     "low", "SILVER",
     "Wording preserved; neutral logistical clause appended."),

    ("handwritten-disgust-2", "paraphrase", "clause_restructuring",
     "Revolted by the taste, he spat out the mouldy bread.",
     "low", "SILVER",
     "Clause order swapped; disgust cue (revolted/mouldy) preserved."),
    ("handwritten-disgust-2", "distractor", "temporal",
     "He spat the mouldy bread out, revolted by the taste. The loaf had been sitting on the counter since Monday.",
     "low", "SILVER",
     "Wording preserved; neutral temporal clause appended."),

    # --- fear ---
    ("dataset-fear-0", "paraphrase", "syntactic",
     "It frightens me that I own it.",
     "medium", "REVIEW",
     "Very short, semantically thin seed; a 7-way model may be unstable, so kept for review."),
    ("dataset-fear-0", "distractor", "administrative",
     "I feel scared that I own it. The receipt is filed in the top drawer.",
     "medium", "REVIEW",
     "Short/ambiguous seed even with wording preserved; flagged for review."),

    ("dataset-fear-1", "paraphrase", "lexical",
     "I feel like someone's odd uncle at a party, trying to break the ice by showing off an amazing talent, expecting the guests to be impressed, but instead making everything a hundred times more awkward.",
     "medium", "REVIEW",
     "Longer social-anxiety seed; meaning preserved, but fear-vs-embarrassment is subtle for a 7-way head."),
    ("dataset-fear-1", "distractor", "temporal",
     "I feel like someone's strange uncle trying to break the ice at a party by showing this amazing talent, thinking that guests will be impressed, but in turn just making everything a hundred times more awkward. The party was held on the second Saturday of the month.",
     "low", "SILVER",
     "Wording preserved; neutral temporal clause appended."),

    ("dataset-fear-2", "paraphrase", "clause_restructuring",
     "A year ago yesterday, I remember feeling so uncertain, so scared of what our future held.",
     "low", "SILVER",
     "Explicit fear cue (scared) preserved; clause reordered."),
    ("dataset-fear-2", "distractor", "ordinary_observation",
     "I can remember, a year ago yesterday, feeling so unsure, so scared of what our future held. The calendar on the wall still showed last month.",
     "low", "SILVER",
     "Wording preserved; neutral observation clause appended."),

    # --- joy (dataset labels are noisy here) ---
    ("dataset-joy-0", "paraphrase", "lexical",
     "I strongly feel that, at this point in my life, I no longer want to walk the path I'm on, and honestly, I have no idea where my life is heading from here.",
     "high", "REVIEW",
     "Dataset label 'joy' is noisy (text reads uncertain/low); 7-way prediction unstable, flagged high."),
    ("dataset-joy-0", "distractor", "logistical",
     "I strongly feel that at this point in my life I am no longer desiring to walk this path that I am on, and to be truthful I have no clue as to where I am going with my life from here. The bus schedule changes at the end of the season.",
     "high", "REVIEW",
     "Noisy underlying label; kept visible for review."),

    ("dataset-joy-1", "paraphrase", "lexical",
     "I read a lot about discovery and exploration in the wild west, and while I find those ideas precious and often take part in them myself, this book simply brings a refined feeling when I sit back in the chair for some quiet time.",
     "medium", "REVIEW",
     "Contentment/joy is mild and diffuse; meaning preserved but re-review for label stability."),
    ("dataset-joy-1", "distractor", "ordinary_observation",
     "I read too much about discovery and exploration in the wild west, and while I feel that those concepts are precious, taking part in them often myself, this book just brings a refined feel when I sit back in the chair for some quiet time. The chair is placed beside the north window.",
     "low", "SILVER",
     "Wording preserved; neutral observation clause appended."),

    ("dataset-joy-2", "paraphrase", "compression",
     "I love feeling valuable, I love making the choice, and I love that it's easy to choose to feel good.",
     "low", "SILVER",
     "Clear repeated joy cue (love/feel good) preserved; lightly compressed."),
    ("dataset-joy-2", "distractor", "mundane_factual",
     "I love that I feel valuable, I love making the choice, I love that it's easy to make the choice to feel good. The notebook where I write this has a plain grey cover.",
     "low", "SILVER",
     "Wording preserved; neutral factual clause appended."),

    # --- neutral (handwritten, clean) ---
    ("handwritten-neutral-0", "paraphrase", "compression",
     "The train leaves platform four at nine a.m.",
     "low", "SILVER",
     "Neutral factual statement; compressed, no affect introduced."),
    ("handwritten-neutral-0", "distractor", "mundane_factual",
     "The train departs from platform four at nine in the morning. A new coat of paint was applied to the railings last week.",
     "low", "SILVER",
     "Wording preserved; second neutral fact appended, still affect-free."),

    ("handwritten-neutral-1", "paraphrase", "lexical",
     "The report has to be submitted by the end of the month.",
     "low", "SILVER",
     "Neutral administrative statement; lexical variation only."),
    ("handwritten-neutral-1", "distractor", "administrative",
     "The report is due at the end of the month. The office has three meeting rooms on this floor.",
     "low", "SILVER",
     "Wording preserved; neutral administrative clause appended."),

    ("handwritten-neutral-2", "paraphrase", "lexical",
     "She set the folder down on the desk and switched the computer on.",
     "low", "SILVER",
     "Neutral action description; lexical variation only."),
    ("handwritten-neutral-2", "distractor", "ordinary_observation",
     "She placed the folder on the desk and turned on the computer. The desk faces a window overlooking the car park.",
     "low", "SILVER",
     "Wording preserved; neutral observation clause appended."),

    # --- sadness ---
    ("dataset-sadness-0", "paraphrase", "lexical",
     "I feel as though the rest of my year will be jaded because of my love for this first one.",
     "medium", "REVIEW",
     "Slightly garbled seed; meaning approximated, so flagged for review."),
    ("dataset-sadness-0", "distractor", "ordinary_observation",
     "I feel as though the rest of my year will be jaded due to my love for this first. The wall calendar lists twelve months on a single page.",
     "medium", "REVIEW",
     "Garbled seed even with wording preserved; kept visible."),

    ("dataset-sadness-1", "paraphrase", "syntactic",
     "I'm feeling quite weepy; can you get rid of them? And she did.",
     "medium", "REVIEW",
     "Weepy cue preserved; disjointed narration makes label less certain, so review."),
    ("dataset-sadness-1", "distractor", "logistical",
     "I am feeling quite weepy, can you get rid of them, and she did. The tissues are kept in the second drawer.",
     "medium", "REVIEW",
     "Disjointed seed; neutral clause appended; kept visible."),

    ("dataset-sadness-2", "paraphrase", "lexical",
     "I walked away from the weekend feeling simply dirty, as if I had done something truly harmful, and more than anything, that feeling overpowers my feeble attempts to justify what I did last weekend.",
     "medium", "REVIEW",
     "Guilt/sadness preserved; long emotional sentence, re-review for shift."),
    ("dataset-sadness-2", "distractor", "temporal",
     "I walked away from the weekend feeling simply dirty, like I had done something really harmful, and this feeling, more than anything, is what overpowers my feeble attempts to justify my actions last weekend. The weekend ran from Friday evening to Sunday night.",
     "low", "SILVER",
     "Wording preserved; neutral temporal clause appended."),

    # --- surprise (short / noisy) ---
    ("dataset-surprise-0", "paraphrase", "lexical",
     "I'm feeling really strange.",
     "high", "REVIEW",
     "Very short/ambiguous ('weird'->'strange'); could read surprise, fear or neutral, so high risk."),
    ("dataset-surprise-0", "distractor", "temporal",
     "I'm feeling really weird. The clock on the wall reads half past three.",
     "high", "REVIEW",
     "Short/ambiguous seed; kept visible for review."),

    ("dataset-surprise-1", "paraphrase", "syntactic",
     "I was overwhelmed by how impressed I felt; I think these kids, they're years younger than me, I can call them kids, right?",
     "medium", "REVIEW",
     "Amazement/surprise cue preserved; conversational aside makes it less clean, review."),
    ("dataset-surprise-1", "distractor", "logistical",
     "I was overwhelmed by the feeling of being impressed. I think these kids, they're years younger than me, I can call them kids, right? The workshop lasted about two hours.",
     "low", "SILVER",
     "Wording preserved; neutral logistical clause appended."),

    ("dataset-surprise-2", "paraphrase", "clause_restructuring",
     "Beside me, I see smiling, and I feel very funny.",
     "high", "REVIEW",
     "Seed is near-nonsense (dataset noise); any paraphrase is approximate, so high risk and review."),
    ("dataset-surprise-2", "distractor", "ordinary_observation",
     "I beside see smiling feel very funny. The room has two windows and a single door.",
     "high", "REVIEW",
     "Garbled seed preserved verbatim; neutral clause appended; kept visible."),
]

SENTIMENT_VARIANTS = [
    # --- NEGATIVE ---
    ("sst2-val-18", "paraphrase", "expansion",
     "In the end, the movie is nothing but a plain old monster.",
     "medium", "REVIEW",
     "Cryptic seed with leading ellipsis; meaning approximated, so review."),
    ("sst2-val-18", "distractor", "logistical",
     "The movie is just a plain old monster. It runs for about ninety minutes.",
     "medium", "REVIEW",
     "Cryptic seed; neutral runtime clause appended; kept visible."),

    ("sst2-val-35", "paraphrase", "lexical",
     "A string of ridiculous shoot-'em-up scenes.",
     "low", "SILVER",
     "Negative cue ('ridiculous') preserved; lexical variation."),
    ("sst2-val-35", "distractor", "mundane_factual",
     "A sequence of ridiculous shoot-'em-up scenes. The film was shot in two countries.",
     "low", "SILVER",
     "Wording preserved; neutral production fact appended."),

    ("sst2-val-59", "paraphrase", "lexical",
     "It's just disappointingly superficial - a film with all the ingredients to be a fascinating, involving character study, yet it never does more than scratch the surface.",
     "low", "SILVER",
     "Clear negative judgement ('disappointingly superficial') preserved."),
    ("sst2-val-59", "distractor", "temporal",
     "It's just disappointingly superficial - a movie that has all the elements necessary to be a fascinating, involving character study, but never does more than scratch the surface. The screening began at seven o'clock.",
     "low", "SILVER",
     "Wording preserved; neutral temporal clause appended."),

    ("sst2-val-110", "paraphrase", "lexical",
     "It earns no points for originality, wit, or intelligence.",
     "low", "SILVER",
     "Strong negative ('no points') preserved."),
    ("sst2-val-110", "distractor", "ordinary_observation",
     "Scores no points for originality, wit, or intelligence. The poster uses three colours.",
     "low", "SILVER",
     "Wording preserved; neutral observation appended."),

    ("sst2-val-111", "paraphrase", "syntactic",
     "There isn't nearly enough fun here, even with some appealing ingredients present.",
     "low", "SILVER",
     "Negative ('not enough fun') preserved despite the concessive clause."),
    ("sst2-val-111", "distractor", "administrative",
     "There isn't nearly enough fun here, despite the presence of some appealing ingredients. The cinema has assigned seating.",
     "low", "SILVER",
     "Wording preserved; neutral administrative clause appended."),

    ("sst2-val-121", "paraphrase", "lexical",
     "It seems to me the film is about the art of ripping people off without ever letting them consciously realise you've done it.",
     "medium", "REVIEW",
     "Sentiment is implicit (descriptive sentence); negativity is inferential, so review."),
    ("sst2-val-121", "distractor", "logistical",
     "It seems to me the film is about the art of ripping people off without ever letting them consciously know you have done so. The plot unfolds across two cities.",
     "medium", "REVIEW",
     "Implicit-sentiment seed; neutral clause appended; kept visible."),

    ("sst2-val-136", "paraphrase", "lexical",
     "It looks and feels like a project that would work better on the small screen.",
     "low", "SILVER",
     "Faint-praise negative ('better suited for TV') preserved."),
    ("sst2-val-136", "distractor", "mundane_factual",
     "Looks and feels like a project better suited for the small screen. The runtime is listed as one hundred minutes.",
     "low", "SILVER",
     "Wording preserved; neutral runtime clause appended."),

    ("sst2-val-162", "paraphrase", "lexical",
     "There seems to be no clear sense of where the story is going, or how long it will take to get there.",
     "low", "SILVER",
     "Negative ('no clear path') preserved."),
    ("sst2-val-162", "distractor", "ordinary_observation",
     "There seems to be no clear path as to where the story's going, or how long it's going to take to get there. The film is divided into three acts.",
     "low", "SILVER",
     "Wording preserved; neutral observation appended."),

    ("sst2-val-211", "paraphrase", "syntactic",
     "Saying this was done better in Wilder's Some Like It Hot is like saying the sun rises in the east.",
     "medium", "REVIEW",
     "Sarcastic comparison; sentiment depends on reading the idiom, so review."),
    ("sst2-val-211", "distractor", "temporal",
     "To say this was done better in Wilder's Some Like It Hot is like saying the sun rises in the east. The earlier film was released decades ago.",
     "medium", "REVIEW",
     "Idiomatic/sarcastic seed; neutral clause appended; kept visible."),

    ("sst2-val-319", "paraphrase", "lexical",
     "Too much of it comes across as unfocused and underdeveloped.",
     "low", "SILVER",
     "Clear negative ('unfocused and underdeveloped') preserved."),
    ("sst2-val-319", "distractor", "mundane_factual",
     "Too much of it feels unfocused and underdeveloped. The director also wrote the screenplay.",
     "low", "SILVER",
     "Wording preserved; neutral production fact appended."),

    # --- POSITIVE ---
    ("sst2-val-13", "paraphrase", "lexical",
     "We root for Clara and Paul, and even like them, though perhaps the feeling is closer to pity.",
     "high", "REVIEW",
     "Mixed sentiment ('closer to pity'); the positive label is fragile, so high risk and review."),
    ("sst2-val-13", "distractor", "temporal",
     "We root for (Clara and Paul), even like them, though perhaps it's an emotion closer to pity. The story is set over a single summer.",
     "high", "REVIEW",
     "Mixed-sentiment seed; neutral clause appended; kept visible."),

    ("sst2-val-17", "paraphrase", "lexical",
     "Audrey Tautou has a knack for choosing roles that magnify her outrageous charm, and in this literate French comedy she's as morning-glory exuberant as she was in Amelie.",
     "low", "SILVER",
     "Strong positive ('outrageous charm', 'exuberant') preserved."),
    ("sst2-val-17", "distractor", "mundane_factual",
     "Audrey Tatou has a knack for picking roles that magnify her outrageous charm, and in this literate French comedy, she's as morning-glory exuberant as she was in Amelie. The comedy is spoken in French.",
     "low", "SILVER",
     "Wording preserved; neutral language fact appended."),

    ("sst2-val-52", "paraphrase", "syntactic",
     "Mr. Tsai is a highly original artist in his medium, and so is What Time Is It There?",
     "medium", "REVIEW",
     "Positive ('very original') preserved, but the film-title clause is awkward, so review."),
    ("sst2-val-52", "distractor", "logistical",
     "Mr. Tsai is a very original artist in his medium, and What Time Is It There? The film had its premiere at a festival.",
     "medium", "REVIEW",
     "Title-as-clause seed; neutral clause appended; kept visible."),

    ("sst2-val-109", "paraphrase", "lexical",
     "It's wonderful escapist fun that recreates a place and time that will never come again.",
     "low", "SILVER",
     "Positive ('great escapist fun') preserved."),
    ("sst2-val-109", "distractor", "mundane_factual",
     "It's great escapist fun that recreates a place and time that will never happen again. The soundtrack features a dozen songs.",
     "low", "SILVER",
     "Wording preserved; neutral soundtrack fact appended."),

    ("sst2-val-120", "paraphrase", "compression",
     "Warm Water Under a Red Bridge is a quirky, poignant Japanese film exploring the fascinating connections between women, water, nature, and sexuality.",
     "low", "SILVER",
     "Positive ('quirky and poignant', 'fascinating') preserved; lightly compressed."),
    ("sst2-val-120", "distractor", "logistical",
     "Warm Water Under a Red Bridge is a quirky and poignant Japanese film that explores the fascinating connections between women, water, nature, and sexuality. The film is roughly two hours long.",
     "low", "SILVER",
     "Wording preserved; neutral runtime clause appended."),

    ("sst2-val-201", "paraphrase", "clause_restructuring",
     "Within the film's conflict-powered plot there's a decent moral trying to get out, but it isn't that - it's the tension that keeps you in your seat.",
     "medium", "REVIEW",
     "Positive resolves late ('tension keeps you in your seat'); structure is tricky, so review."),
    ("sst2-val-201", "distractor", "administrative",
     "Inside the film's conflict-powered plot there is a decent moral trying to get out, but it's not that, it's the tension that keeps you in your seat. The film is rated for general audiences.",
     "low", "SILVER",
     "Wording preserved; neutral rating clause appended."),

    ("sst2-val-227", "paraphrase", "lexical",
     "As the two leads, Lathan and Diggs are charming and share chemistry both as friends and as lovers.",
     "low", "SILVER",
     "Positive ('charming', 'chemistry') preserved."),
    ("sst2-val-227", "distractor", "ordinary_observation",
     "As the two leads, Lathan and Diggs are charming and have chemistry both as friends and lovers. The pair appear in most of the film's scenes.",
     "low", "SILVER",
     "Wording preserved; neutral observation appended."),

    ("sst2-val-248", "paraphrase", "lexical",
     "A complete world has been presented onscreen, rather than a series of carefully structured plot points building to a pat resolution.",
     "medium", "REVIEW",
     "Positive is comparative/implicit ('a full world, not... pat resolution'), so review."),
    ("sst2-val-248", "distractor", "logistical",
     "A full world has been presented onscreen, not some series of carefully structured plot points building to a pat resolution. The film uses several outdoor locations.",
     "low", "SILVER",
     "Wording preserved; neutral location clause appended."),

    ("sst2-val-290", "paraphrase", "lexical",
     "Deliriously funny, fast and loose, easy for newcomers to enjoy, and full of surprises.",
     "low", "SILVER",
     "Strongly positive list ('deliriously funny', 'full of surprises') preserved."),
    ("sst2-val-290", "distractor", "temporal",
     "Deliriously funny, fast and loose, accessible to the uninitiated, and full of surprises. The screening lasted a little under two hours.",
     "low", "SILVER",
     "Wording preserved; neutral temporal clause appended."),

    ("sst2-val-341", "paraphrase", "clause_restructuring",
     "Anyone with even a passing interest in the events shaping the world beyond their own horizons deserves to see it.",
     "low", "SILVER",
     "Positive recommendation ('deserves to be seen') preserved; clause reordered."),
    ("sst2-val-341", "distractor", "mundane_factual",
     "It deserves to be seen by anyone with even a passing interest in the events shaping the world beyond their own horizons. The documentary includes archival footage.",
     "low", "SILVER",
     "Wording preserved; neutral factual clause appended."),
]
