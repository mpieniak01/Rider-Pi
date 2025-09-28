"""Test suite for PTT state machine."""

import time

import pytest

from apps.voice.stream.state import PTTEvent, PTTState, PTTStateMachine


class TestPTTStateMachine:
    """Test PTT state machine behavior."""

    def test_initial_state(self):
        """Test initial state is IDLE."""
        fsm = PTTStateMachine()
        assert fsm.state == PTTState.IDLE
        assert not fsm.is_active()
        assert not fsm.is_recording()
        assert not fsm.is_speaking()

    def test_basic_transition(self):
        """Test basic state transition."""
        fsm = PTTStateMachine()

        result = fsm.transition(PTTEvent.START)

        assert result is True  # Transition occurred
        assert fsm.state == PTTState.ARMING
        assert fsm.is_active()

    def test_invalid_transition(self):
        """Test invalid transition doesn't change state."""
        fsm = PTTStateMachine()

        # VOICE_START from IDLE is invalid
        result = fsm.transition(PTTEvent.VOICE_START)

        assert result is False  # No transition
        assert fsm.state == PTTState.IDLE

    def test_complete_interaction_flow(self):
        """Test complete PTT interaction flow."""
        fsm = PTTStateMachine()

        # Start interaction
        fsm.start_interaction()
        assert fsm.transition(PTTEvent.START)
        assert fsm.state == PTTState.ARMING

        # Ready to record
        assert fsm.transition(PTTEvent.DING_COMPLETE)
        assert fsm.state == PTTState.RECORDING
        assert fsm.is_recording()

        # Voice detected and ended
        assert fsm.transition(PTTEvent.VOICE_END)
        assert fsm.state == PTTState.COMMIT

        # Server response received
        assert fsm.transition(PTTEvent.SERVER_RESPONSE)
        assert fsm.state == PTTState.WAIT_REPLY

        # TTS starts playing
        assert fsm.transition(PTTEvent.TTS_START)
        assert fsm.state == PTTState.SPEAKING
        assert fsm.is_speaking()

        # TTS finished
        assert fsm.transition(PTTEvent.TTS_COMPLETE)
        assert fsm.state == PTTState.CLOSING

        # Auto-transition to IDLE
        assert fsm.transition(PTTEvent.TIMEOUT)  # Any event works from CLOSING
        assert fsm.state == PTTState.IDLE

    def test_error_transition_from_any_state(self):
        """Test ERROR event transitions from any state."""
        fsm = PTTStateMachine()

        # Start in RECORDING
        fsm.transition(PTTEvent.START)
        fsm.transition(PTTEvent.DING_COMPLETE)
        assert fsm.state == PTTState.RECORDING

        # Error should transition to ERROR state
        assert fsm.transition(PTTEvent.ERROR)
        assert fsm.state == PTTState.ERROR

    def test_cancel_transition_from_any_state(self):
        """Test CANCEL event transitions to IDLE from any state."""
        fsm = PTTStateMachine()

        # Start in SPEAKING
        fsm.transition(PTTEvent.START)
        fsm.transition(PTTEvent.DING_COMPLETE)
        fsm.transition(PTTEvent.VOICE_END)
        fsm.transition(PTTEvent.TTS_START)
        assert fsm.state == PTTState.SPEAKING

        # Cancel should return to IDLE
        assert fsm.transition(PTTEvent.CANCEL)
        assert fsm.state == PTTState.IDLE

    def test_timeout_handling(self):
        """Test timeout handling in various states."""
        fsm = PTTStateMachine()

        # Timeout from ARMING should go to IDLE
        fsm.transition(PTTEvent.START)
        assert fsm.state == PTTState.ARMING

        assert fsm.transition(PTTEvent.TIMEOUT)
        assert fsm.state == PTTState.IDLE

    def test_barge_in_during_speaking(self):
        """Test interruption during TTS playback."""
        fsm = PTTStateMachine()

        # Get to SPEAKING state
        fsm.transition(PTTEvent.START)
        fsm.transition(PTTEvent.DING_COMPLETE)
        fsm.transition(PTTEvent.VOICE_END)
        fsm.transition(PTTEvent.TTS_START)
        assert fsm.state == PTTState.SPEAKING

        # New START event should allow barge-in
        assert fsm.transition(PTTEvent.START)
        assert fsm.state == PTTState.ARMING

    def test_state_callbacks(self):
        """Test state entry/exit callbacks."""
        fsm = PTTStateMachine()

        enter_calls = []
        exit_calls = []
        transition_calls = []

        def on_enter():
            enter_calls.append(fsm.state)

        def on_exit():
            exit_calls.append(fsm.state)

        def on_transition(event):
            transition_calls.append((fsm.state, event))

        # Add callbacks
        fsm.add_enter_callback(PTTState.ARMING, on_enter)
        fsm.add_exit_callback(PTTState.IDLE, on_exit)
        fsm.add_transition_callback(PTTState.IDLE, PTTState.ARMING, on_transition)

        # Trigger transition
        fsm.transition(PTTEvent.START)

        # Check callbacks were called
        assert PTTState.ARMING in enter_calls
        assert PTTState.IDLE in exit_calls
        assert (PTTState.ARMING, PTTEvent.START) in transition_calls

    def test_reset(self):
        """Test state machine reset."""
        fsm = PTTStateMachine()

        # Get to some active state
        fsm.transition(PTTEvent.START)
        fsm.transition(PTTEvent.DING_COMPLETE)
        assert fsm.state == PTTState.RECORDING
        assert fsm.is_active()

        # Reset should return to IDLE
        fsm.reset()
        assert fsm.state == PTTState.IDLE
        assert not fsm.is_active()

    def test_can_interrupt(self):
        """Test interrupt capability check."""
        fsm = PTTStateMachine()

        # IDLE allows interruption
        assert fsm.can_interrupt()

        # RECORDING doesn't allow interruption
        fsm.transition(PTTEvent.START)
        fsm.transition(PTTEvent.DING_COMPLETE)
        assert fsm.state == PTTState.RECORDING
        assert not fsm.can_interrupt()

        # SPEAKING allows interruption (barge-in)
        fsm.transition(PTTEvent.VOICE_END)
        fsm.transition(PTTEvent.TTS_START)
        assert fsm.state == PTTState.SPEAKING
        assert fsm.can_interrupt()

    def test_duration_tracking(self):
        """Test state duration tracking."""
        fsm = PTTStateMachine()

        fsm.start_interaction()

        # Small delay to test duration
        time.sleep(0.01)

        fsm.transition(PTTEvent.START)

        # Check durations are tracked
        state_duration = fsm.get_state_duration_ms()
        total_duration = fsm.get_total_duration_ms()

        assert state_duration >= 0
        assert total_duration >= state_duration

        fsm.end_interaction()

        # Total duration should reset
        assert fsm.get_total_duration_ms() == 0

    def test_error_recovery(self):
        """Test recovery from error state."""
        fsm = PTTStateMachine()

        # Get to error state
        fsm.transition(PTTEvent.ERROR)
        assert fsm.state == PTTState.ERROR

        # Should be able to start new interaction
        assert fsm.transition(PTTEvent.START)
        assert fsm.state == PTTState.ARMING

        # Also test timeout recovery
        fsm.transition(PTTEvent.ERROR)
        assert fsm.transition(PTTEvent.TIMEOUT)
        assert fsm.state == PTTState.IDLE
