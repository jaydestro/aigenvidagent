"""Dependency-free validation shared by narration and capture entrypoints."""
import math
from fractions import Fraction


def finite_number(value, name, minimum=0):
    number = float(value)
    if not math.isfinite(number) or number < minimum:
        raise ValueError(f"{name} must be finite and >= {minimum}")
    return number


def frame_count(seconds, fps):
    finite_number(seconds, "duration")
    finite_number(fps, "fps", 1)
    frames = Fraction(str(seconds)) * Fraction(str(fps))
    if frames.denominator != 1:
        raise ValueError("duration must be exactly representable at the requested fps")
    return int(frames)


def narration_fits(end, minimum, maximum):
    finite_number(end, "narration end")
    finite_number(minimum, "min-end")
    finite_number(maximum, "max-end")
    end, minimum, maximum = (
        Fraction(str(value)) for value in (end, minimum, maximum)
    )
    if minimum > maximum:
        raise ValueError("min-end must not exceed max-end")
    return minimum <= end <= maximum


def validate_finish(total, audio_end, narration_end, hold):
    finite_number(total, "duration")
    finite_number(audio_end, "audio duration")
    finite_number(narration_end, "narration end")
    finite_number(hold, "hold")
    finish, audio, narration, final_hold = (
        Fraction(str(value))
        for value in (total, audio_end, narration_end, hold)
    )
    if finish < audio or finish < narration + final_hold:
        raise ValueError("duration would cut narration or its declared final hold")
    return float(total)