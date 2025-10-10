# apps/voice/tests/test_state_ptt.py
"""Test PTT state machine functionality."""
import asyncio

from apps.voice.stream.state import PTTEvent, PTTStateMachine


def test_ptt_state_transitions():
    """Test basic PTT state machine transitions."""
    sm = PTTStateMachine()
    
    # Initial state should be IDLE
    from apps.voice.stream.state import PTTState
    assert sm.state == PTTState.IDLE
    
    # START event should transition to ARMING
    sm.transition(PTTEvent.START)
    assert sm.state == PTTState.ARMING
    
    # DING_COMPLETE should transition to RECORDING
    sm.transition(PTTEvent.DING_COMPLETE)
    assert sm.state == PTTState.RECORDING
    
    # COMMIT_AUDIO should transition to COMMIT
    sm.transition(PTTEvent.COMMIT_AUDIO)
    assert sm.state == PTTState.COMMIT
    
    # TTS_START should transition to SPEAKING
    sm.transition(PTTEvent.TTS_START)
    assert sm.state == PTTState.SPEAKING
    
    # TTS_COMPLETE should transition to CLOSING
    sm.transition(PTTEvent.TTS_COMPLETE)
    assert sm.state == PTTState.CLOSING


def test_ptt_state_callbacks():
    """Test that state transition callbacks are invoked."""
    sm = PTTStateMachine()
    from apps.voice.stream.state import PTTState
    
    callback_called = {"value": False, "event": None}
    
    def on_transition(event: PTTEvent):
        callback_called["value"] = True
        callback_called["event"] = event
    
    # Add callback for IDLE -> ARMING transition
    sm.add_transition_callback(PTTState.IDLE, PTTState.ARMING, on_transition)
    
    # Trigger transition
    sm.transition(PTTEvent.START)
    
    # Callback should have been called
    assert callback_called["value"] is True
    assert callback_called["event"] == PTTEvent.START
    assert sm.state == PTTState.ARMING


def test_ptt_state_enter_exit_callbacks():
    """Test state entry and exit callbacks."""
    sm = PTTStateMachine()
    from apps.voice.stream.state import PTTState
    
    enter_called = {"value": False}
    exit_called = {"value": False}
    
    def on_enter():
        enter_called["value"] = True
    
    def on_exit():
        exit_called["value"] = True
    
    # Add enter callback for ARMING
    sm.add_enter_callback(PTTState.ARMING, on_enter)
    # Add exit callback for IDLE
    sm.add_exit_callback(PTTState.IDLE, on_exit)
    
    # Trigger transition from IDLE to ARMING
    sm.transition(PTTEvent.START)
    
    # Both callbacks should have been called
    assert exit_called["value"] is True
    assert enter_called["value"] is True
