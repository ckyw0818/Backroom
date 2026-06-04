from ursina import Audio, destroy, invoke


def set_audio_pitch(sound, pitch):
    for attr in ('pitch', 'play_rate', 'rate'):
        if hasattr(sound, attr):
            try:
                setattr(sound, attr, pitch)
                return
            except Exception:
                pass

    for attr in ('sound', '_sound', 'audio', '_audio'):
        inner = getattr(sound, attr, None)

        if inner and hasattr(inner, 'setPlayRate'):
            try:
                inner.setPlayRate(pitch)
                return
            except Exception:
                pass


def cleanup_audio(sound):
    try:
        sound.stop()
    except Exception:
        pass

    try:
        destroy(sound)
    except Exception:
        pass


def play_transient_sound(path, volume=1.0, pitch=None, start=None, ttl=3.0):
    sound = Audio(path, autoplay=False, volume=volume)

    if pitch is not None:
        set_audio_pitch(sound, pitch)

    if start is None:
        sound.play()
    else:
        sound.play(start=start)

    invoke(cleanup_audio, sound, delay=ttl)
    return sound
