"""MusicXML generation and parsing. Timing is expressed in quarter notes."""

from dataclasses import dataclass
from pathlib import Path

from music21 import chord, clef, converter, instrument, key, metadata, meter, note, stream, tempo


@dataclass(frozen=True)
class NoteEvent:
    """A written note; beat is 1-based, onset and duration use quarter-note units.

    IDs encode part, measure ordinal, and note ordinal, so repeated parsing of
    the same score is stable even when MusicXML has no explicit note IDs.
    Tied segments remain separate written events in this baseline.
    """

    id: str
    measure: int
    beat: float
    pitch: str
    midi: float
    onset_quarters: float
    duration_quarters: float


def generate_score(path: str | Path) -> Path:
    """Write eight bars of Ode to Joy in D major, 4/4, quarter = 88."""
    score = stream.Score(id="quartetiq-ode")
    score.metadata = metadata.Metadata(title="Ode to Joy — solo violin", composer="Ludwig van Beethoven")
    part = stream.Part(id="violin")
    part.insert(0, instrument.Violin())
    bars = [
        [("F#4", 1), ("F#4", 1), ("G4", 1), ("A4", 1)],
        [("A4", 1), ("G4", 1), ("F#4", 1), ("E4", 1)],
        [("D4", 1), ("D4", 1), ("E4", 1), ("F#4", 1)],
        [("F#4", 1.5), ("E4", .5), ("E4", 2)],
        [("F#4", 1), ("F#4", 1), ("G4", 1), ("A4", 1)],
        [("A4", 1), ("G4", 1), ("F#4", 1), ("E4", 1)],
        [("D4", 1), ("D4", 1), ("E4", 1), ("F#4", 1)],
        [("E4", 1.5), ("D4", .5), ("D4", 2)],
    ]
    for number, pitches in enumerate(bars, 1):
        measure = stream.Measure(number=number)
        if number == 1:
            for marking in (clef.TrebleClef(), key.Key("D"), meter.TimeSignature("4/4"), tempo.MetronomeMark(number=88)):
                measure.insert(0, marking)
        for pitch, duration in pitches:
            measure.append(note.Note(pitch, quarterLength=duration))
        part.append(measure)
    score.append(part)
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    score.write("musicxml", fp=output)
    return output


def parse_score(path: str | Path) -> list[NoteEvent]:
    """Parse one monophonic part, retaining rests as gaps; reject polyphony.

    Beat follows the MusicXML time signature. Repeats are not expanded and
    tempo markings do not affect quarter-note offsets.
    """
    score = converter.parse(str(path))
    if len(score.parts) != 1:
        raise ValueError("Expected exactly one monophonic part")
    part = score.parts[0]
    events: list[NoteEvent] = []
    end = 0.0
    for measure_index, measure in enumerate(part.getElementsByClass(stream.Measure), 1):
        for index, item in enumerate(measure.recurse().notes, 1):
            if isinstance(item, chord.Chord):
                raise ValueError("Chords are not supported")
            onset = float(item.getOffsetInHierarchy(part))
            duration = float(item.quarterLength)
            if duration <= 0 or onset < end - 1e-9:
                raise ValueError("Overlapping or zero-duration notes are not supported")
            events.append(NoteEvent(
                id=f"p1-m{measure_index:03d}-n{index:03d}",
                measure=int(measure.number), beat=float(item.beat),
                pitch=item.pitch.nameWithOctave, midi=float(item.pitch.ps),
                onset_quarters=onset, duration_quarters=duration,
            ))
            end = onset + duration
    if not events:
        raise ValueError("Score contains no notes")
    return events
