from ursina import Audio


TRANSIENT_VOICES_PER_SOUND = 4
_sound_pools = {}
_sound_pool_indices = {}


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


def _get_sound_pool(path):
    key = str(path)
    pool = _sound_pools.get(key)

    if pool is None:
        pool = [
            Audio(key, autoplay=False, volume=0.0)
            for _ in range(TRANSIENT_VOICES_PER_SOUND)
        ]
        _sound_pools[key] = pool
        _sound_pool_indices[key] = 0

    return key, pool


def cleanup_audio(sound):
    if not sound:
        return

    try:
        sound.stop()
    except Exception:
        pass


def play_transient_sound(path, volume=1.0, pitch=None, start=None, ttl=3.0):
    key, pool = _get_sound_pool(path)
    index = _sound_pool_indices[key] % len(pool)
    _sound_pool_indices[key] = index + 1
    sound = pool[index]

    try:
        sound.stop()
    except Exception:
        pass

    sound.volume = volume
    set_audio_pitch(sound, pitch if pitch is not None else 1.0)

    if start is None:
        sound.play()
    else:
        sound.play(start=start)

    return sound
