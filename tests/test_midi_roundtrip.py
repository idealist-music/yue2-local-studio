import unittest
from fractions import Fraction

from studio.midi_codec import MidiFile, MidiTrack, MidiNote, write, parse


class MidiRoundtripModelTests(unittest.TestCase):
    def test_off_before_on_is_well_formed_output(self):
        data = write(MidiFile(1, 15360, [MidiTrack("Vocal", [MidiNote(0, 60, 100, 0, 15360), MidiNote(0, 60, 100, 15360, 30720)])]))
        parsed = parse(data)
        self.assertEqual([(n.start, n.end) for n in parsed.tracks[1].notes], [(0, 15360), (15360, 30720)])

    def test_fraction_is_exact(self):
        self.assertEqual(Fraction(3, 8) * 15360, 5760)
