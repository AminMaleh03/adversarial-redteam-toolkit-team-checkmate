"""Supplies the disgust-label baseline sentences."""

"""
Hand-written DISGUST sentences.

dair-ai/emotion has no `disgust` label, but the model predicts one, so
these are written by hand and marked source="handwritten" in the
baseline. Kept plainly and obviously disgust -- clear revulsion --
since we can't lean on a dataset label to justify them.
"""

DISGUST_SENTENCES = [
    "The milk had curdled into lumps and the smell made me gag.",
    "There were maggots crawling through the rotting meat in the bin.",
    "He spat the mouldy bread out, revolted by the taste.",
    "The bathroom was smeared with filth and reeked of sewage.",
    "Cockroaches scattered across the greasy, food-crusted counter.",
    "The rotten eggs oozed a foul, sulphuric slime.",
]