"""A clip the planner picks never stops mid-sentence: the model's ranges (whole seconds read off a m:ss transcript)
are snapped to the sentences around them."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from vstudio.intake.plan import SNAP_TAIL_S, snap_to_sentences  # noqa: E402

S = [dict(t=60.85, te=66.22, text="If you stumble, just restart the sentence."),
     dict(t=67.83, te=73.35, text="The editor keeps the last good take and drops the rest."),
     dict(t=75.55, te=78.92, text="The third habit is to let the batch do the boring part."),
     dict(t=79.52, te=96.0, text="A very long sentence that goes on and on for a long time without stopping.")]


def test_end_goes_to_the_end_of_its_sentence():
    a, b = snap_to_sentences(61.0, 70.0, S)
    assert (a, b) == (60.85, 73.35 + SNAP_TAIL_S)               # 70 s cut "The editor keeps the last good take and|"


def test_end_far_from_its_sentence_end_goes_back_to_the_one_before():
    a, b = snap_to_sentences(60.0, 82.0, S)                     # 82 s is 14 s before that sentence ends
    assert b == 78.92 + SNAP_TAIL_S


def test_start_goes_back_to_its_sentence_and_ranges_in_gaps_stay():
    assert snap_to_sentences(69.0, 74.0, S)[0] == 67.83
    assert snap_to_sentences(66.5, 74.5, S) == (66.5, 74.5)    # both in pauses: already on sentence edges
    assert snap_to_sentences(61.0, 70.0, [], 100) == (61.0, 70.0)
