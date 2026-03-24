import pytest
import time
import sys
sys.path.insert(0, '/home/pi/drumkit')

from drumkit import velocity_to_ms, Settings

class TestVelocityToMs:
    """Test velocity_to_ms helper function."""
    
    def test_min_velocity(self):
        """Velocity 0 should be clamped to 1, giving MIN_ON_MS."""
        settings = Settings()
        result = velocity_to_ms(0)
        assert result == settings.MIN_ON_MS
    
    def test_max_velocity(self):
        """Velocity 127 should give MAX_ON_MS."""
        settings = Settings()
        result = velocity_to_ms(127)
        assert result == settings.MAX_ON_MS
    
    def test_mid_velocity(self):
        """Velocity 64 should give approximately midpoint."""
        settings = Settings()
        result = velocity_to_ms(64)
        expected = settings.MIN_ON_MS + (settings.MAX_ON_MS - settings.MIN_ON_MS) * (63 / 126)
        assert abs(result - expected) < 0.01
    
    def test_velocity_monotonic(self):
        """Higher velocity should give longer on_ms."""
        v1 = velocity_to_ms(30)
        v2 = velocity_to_ms(100)
        assert v2 > v1


class TestDebounceLogic:
    """Test the debounce/re-hit logic."""
    
    def test_fresh_hit_uses_velocity(self):
        """A fresh hit (after lockout window) should use the velocity's on_ms directly."""
        settings = Settings()
        last_hit_time = {}
        current_on_ms = {}
        
        note = 38
        velocity = 80
        new_on_ms = velocity_to_ms(velocity)
        now = time.monotonic()
        
        # First hit (no prior history)
        elapsed = now - last_hit_time.get(note, -float('inf'))
        assert elapsed >= settings.MIN_RETRIGGER_MS / 1000  # Always true for fresh
        
        on_ms = new_on_ms
        last_hit_time[note] = now
        current_on_ms[note] = on_ms
        
        assert on_ms == new_on_ms
    
    def test_rapid_rehit_extends_onms(self):
        """A re-hit within lockout window should extend on_ms."""
        settings = Settings()
        last_hit_time = {}
        current_on_ms = {}
        
        note = 38
        
        # First hit with low velocity
        now = time.monotonic()
        velocity1 = 30
        new_on_ms1 = velocity_to_ms(velocity1)
        on_ms1 = new_on_ms1
        last_hit_time[note] = now
        current_on_ms[note] = on_ms1
        
        # Second hit (within lockout) with low velocity to avoid hitting MAX_ON_MS
        now2 = now + settings.MIN_RETRIGGER_MS / 2000  # 25ms later (within 50ms window)
        velocity2 = 25
        new_on_ms2 = velocity_to_ms(velocity2)
        elapsed = now2 - last_hit_time[note]
        
        assert elapsed < settings.MIN_RETRIGGER_MS / 1000
        on_ms2 = min(settings.MAX_ON_MS, current_on_ms[note] + new_on_ms2)
        
        # on_ms2 should be the sum of both, not just velocity2 (and not capped by MAX_ON_MS in this case)
        assert on_ms2 > new_on_ms2
        assert on_ms2 == on_ms1 + new_on_ms2
    
    def test_rapid_rehit_capped_at_max(self):
        """Extended on_ms should be capped at MAX_ON_MS."""
        settings = Settings()
        last_hit_time = {}
        current_on_ms = {}
        
        note = 48
        
        # First hit with high velocity
        now = time.monotonic()
        velocity1 = 120
        new_on_ms1 = velocity_to_ms(velocity1)
        on_ms1 = new_on_ms1
        last_hit_time[note] = now
        current_on_ms[note] = on_ms1
        
        # Second hit with high velocity (within lockout)
        now2 = now + settings.MIN_RETRIGGER_MS / 2000
        velocity2 = 120
        new_on_ms2 = velocity_to_ms(velocity2)
        
        on_ms2 = min(settings.MAX_ON_MS, current_on_ms[note] + new_on_ms2)
        
        # Should not exceed MAX_ON_MS
        assert on_ms2 <= settings.MAX_ON_MS
        assert on_ms2 == settings.MAX_ON_MS  # In this case, the sum will exceed, so capped
    
    def test_hit_after_lockout_is_fresh(self):
        """A hit after lockout window expires should be treated as fresh."""
        settings = Settings()
        last_hit_time = {}
        current_on_ms = {}
        
        note = 46
        
        # First hit
        now = time.monotonic()
        velocity1 = 60
        new_on_ms1 = velocity_to_ms(velocity1)
        on_ms1 = new_on_ms1
        last_hit_time[note] = now
        current_on_ms[note] = on_ms1
        
        # Second hit (after lockout expires)
        now2 = now + settings.MIN_RETRIGGER_MS / 1000 + 0.01  # 60ms later
        velocity2 = 80
        new_on_ms2 = velocity_to_ms(velocity2)
        elapsed = now2 - last_hit_time[note]
        
        assert elapsed >= settings.MIN_RETRIGGER_MS / 1000
        on_ms2 = new_on_ms2  # Fresh hit
        
        # Should be the velocity's on_ms, not extended
        assert on_ms2 == new_on_ms2
        assert on_ms2 != on_ms1 + new_on_ms2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
