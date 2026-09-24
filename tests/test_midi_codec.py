import unittest

from studio.midi_codec import MidiError, MidiFile, MidiTrack, MidiNote, parse, write


class MidiCodecTests(unittest.TestCase):
    def test_type_one_roundtrip(self):
        source = MidiFile(1, 960, [MidiTrack("Vocal", [MidiNote(0, 60, 100, 0, 480)])], tempo=[(0, 500000)])
        data = write(source)
        result = parse(data)
        self.assertEqual(result.ppq, 960)
        self.assertEqual(result.tracks[1].notes[0].end, 480)

    def test_rejects_smpte(self):
        data = b"MThd" + (6).to_bytes(4, "big") + (0).to_bytes(2, "big") + (1).to_bytes(2, "big") + (0xE728).to_bytes(2, "big")
        with self.assertRaises(MidiError):
            parse(data)
