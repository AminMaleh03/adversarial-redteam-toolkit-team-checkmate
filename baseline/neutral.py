"""Supplies the neutral-label baseline sentences."""

"""
Hand-written NEUTRAL sentences.

dair-ai/emotion has no `neutral` label, but the model predicts one, so
these are written by hand and marked source="handwritten" in the
baseline. Kept plainly and obviously neutral -- flat, factual, no
emotional content -- since we can't lean on a dataset label to justify
them.
"""

NEUTRAL_SENTENCES = [
    "The train departs from platform four at nine in the morning.",
    "The report is due at the end of the month.",
    "She placed the folder on the desk and turned on the computer.",
    "The meeting has been moved to the third-floor conference room.",
    "Water boils at one hundred degrees Celsius at sea level.",
    "The store closes at eight on weekdays.",
]