"""PTT (Push-to-Talk) state machine for Rider-Pi voice assistant.

Implements a clean state machine for voice interaction flows:
IDLE → ARMING → RECORDING → COMMIT → WAIT_REPLY → SPEAKING → CLOSING → IDLE
"""

from __future__ import annotations

import time
from enum import Enum, auto
from typing import Callable

from .. import voice_logging


class PTTState(Enum):
    """PTT state machine states."""
    IDLE = auto()         # Waiting for user input
    ARMING = auto()       # Preparing to record (ding, etc.)
    RECORDING = auto()    # Capturing audio
    COMMIT = auto()       # Finalizing recording, sending to server  
    WAIT_REPLY = auto()   # Waiting for server response
    SPEAKING = auto()     # Playing TTS response
    CLOSING = auto()      # Cleaning up after response
    ERROR = auto()        # Error state


class PTTEvent(Enum):
    """PTT state machine events."""
    START = auto()         # User initiated interaction (key press, hotword)
    DING_COMPLETE = auto() # Ready to record after ding
    VOICE_START = auto()   # Voice activity detected
    VOICE_END = auto()     # Voice activity ended
    COMMIT_AUDIO = auto()  # Force commit current audio
    SERVER_RESPONSE = auto() # Server sent response
    TTS_START = auto()     # TTS playback started
    TTS_COMPLETE = auto()  # TTS playback finished
    CANCEL = auto()        # Cancel current interaction
    ERROR = auto()         # Error occurred
    TIMEOUT = auto()       # Operation timeout


class PTTStateMachine:
    """PTT state machine with event handling and callbacks."""

    def __init__(self, logger: voice_logging.VoiceLogger | None = None):
        self.logger = logger or voice_logging.get_logger(__name__)
        self.state = PTTState.IDLE
        self.start_time: float = 0
        self.last_transition: float = 0
        
        # Callbacks for state transitions
        self.callbacks: dict[tuple[PTTState, PTTState], list[Callable[[PTTEvent], None]]] = {}
        
        # State entry/exit callbacks
        self.on_enter: dict[PTTState, list[Callable[[], None]]] = {}
        self.on_exit: dict[PTTState, list[Callable[[], None]]] = {}

    def add_transition_callback(self, from_state: PTTState, to_state: PTTState,
                              callback: Callable[[PTTEvent], None]) -> None:
        """Add callback for specific state transition."""
        key = (from_state, to_state)
        if key not in self.callbacks:
            self.callbacks[key] = []
        self.callbacks[key].append(callback)

    def add_enter_callback(self, state: PTTState, callback: Callable[[], None]) -> None:
        """Add callback for entering a state."""
        if state not in self.on_enter:
            self.on_enter[state] = []
        self.on_enter[state].append(callback)

    def add_exit_callback(self, state: PTTState, callback: Callable[[], None]) -> None:
        """Add callback for exiting a state."""
        if state not in self.on_exit:
            self.on_exit[state] = []
        self.on_exit[state].append(callback)

    def transition(self, event: PTTEvent) -> bool:
        """Process event and transition state if valid.
        
        Args:
            event: Event to process
            
        Returns:
            True if state transition occurred
        """
        old_state = self.state
        new_state = self._next_state(self.state, event)
        
        if new_state == self.state:
            # No state change
            return False
            
        # Log transition
        self.logger.event("ptt.transition",
                         from_state=old_state.name,
                         to_state=new_state.name,
                         event=event.name,
                         duration_ms=int((time.time() - self.last_transition) * 1000))
        
        # Execute exit callbacks
        for callback in self.on_exit.get(old_state, []):
            try:
                callback()
            except Exception as e:
                self.logger.event("ptt.callback.exit_error", 
                                state=old_state.name, error=str(e))
        
        # Update state
        self.state = new_state
        self.last_transition = time.time()
        
        # Execute transition callbacks
        key = (old_state, new_state)
        for callback in self.callbacks.get(key, []):
            try:
                callback(event)
            except Exception as e:
                self.logger.event("ptt.callback.transition_error",
                                from_state=old_state.name,
                                to_state=new_state.name,
                                error=str(e))
        
        # Execute enter callbacks
        for callback in self.on_enter.get(new_state, []):
            try:
                callback()
            except Exception as e:
                self.logger.event("ptt.callback.enter_error",
                                state=new_state.name, error=str(e))
        
        return True

    def _next_state(self, current: PTTState, event: PTTEvent) -> PTTState:
        """Determine next state based on current state and event."""
        # Error and cancel handling - can happen from any state
        if event == PTTEvent.ERROR:
            return PTTState.ERROR
        if event == PTTEvent.CANCEL:
            return PTTState.IDLE
            
        # State-specific transitions
        if current == PTTState.IDLE:
            if event == PTTEvent.START:
                return PTTState.ARMING
                
        elif current == PTTState.ARMING:
            if event == PTTEvent.DING_COMPLETE:
                return PTTState.RECORDING
            if event == PTTEvent.TIMEOUT:
                return PTTState.IDLE
                
        elif current == PTTState.RECORDING:
            if event == PTTEvent.VOICE_END:
                return PTTState.COMMIT
            if event == PTTEvent.COMMIT_AUDIO:
                return PTTState.COMMIT
            if event == PTTEvent.TIMEOUT:
                return PTTState.COMMIT
                
        elif current == PTTState.COMMIT:
            if event == PTTEvent.SERVER_RESPONSE:
                return PTTState.WAIT_REPLY  # Expecting more responses
            if event == PTTEvent.TTS_START:
                return PTTState.SPEAKING
            if event == PTTEvent.TIMEOUT:
                return PTTState.IDLE
                
        elif current == PTTState.WAIT_REPLY:
            if event == PTTEvent.SERVER_RESPONSE:
                return PTTState.WAIT_REPLY  # Still waiting
            if event == PTTEvent.TTS_START:
                return PTTState.SPEAKING
            if event == PTTEvent.TIMEOUT:
                return PTTState.IDLE
                
        elif current == PTTState.SPEAKING:
            if event == PTTEvent.TTS_COMPLETE:
                return PTTState.CLOSING
            # Allow interruption during speaking
            if event == PTTEvent.START:
                return PTTState.ARMING
                
        elif current == PTTState.CLOSING:
            # Always return to idle after closing
            return PTTState.IDLE
            
        elif current == PTTState.ERROR:
            # Can recover from error
            if event == PTTEvent.START:
                return PTTState.ARMING
            # Auto-recovery after timeout
            if event == PTTEvent.TIMEOUT:
                return PTTState.IDLE
        
        # No valid transition - stay in current state
        return current

    def reset(self) -> None:
        """Reset state machine to IDLE."""
        old_state = self.state
        if old_state != PTTState.IDLE:
            # Execute exit callbacks for current state
            for callback in self.on_exit.get(old_state, []):
                try:
                    callback()
                except Exception as e:
                    self.logger.event("ptt.callback.exit_error",
                                    state=old_state.name, error=str(e))
            
            self.state = PTTState.IDLE
            self.last_transition = time.time()
            
            self.logger.event("ptt.reset", from_state=old_state.name)

    def is_active(self) -> bool:
        """Check if state machine is in an active (non-idle) state."""
        return self.state != PTTState.IDLE

    def is_recording(self) -> bool:
        """Check if currently recording audio."""
        return self.state == PTTState.RECORDING

    def is_speaking(self) -> bool:
        """Check if currently playing TTS."""
        return self.state == PTTState.SPEAKING

    def can_interrupt(self) -> bool:
        """Check if current state allows interruption."""
        # Can interrupt during speaking or in error state
        return self.state in (PTTState.SPEAKING, PTTState.ERROR, PTTState.IDLE)

    def get_state_duration_ms(self) -> int:
        """Get time spent in current state in milliseconds."""
        return int((time.time() - self.last_transition) * 1000)

    def get_total_duration_ms(self) -> int:
        """Get total interaction duration in milliseconds."""
        if self.start_time == 0:
            return 0
        return int((time.time() - self.start_time) * 1000)

    def start_interaction(self) -> None:
        """Mark start of interaction session."""
        self.start_time = time.time()
        self.last_transition = time.time()
        self.logger.event("ptt.interaction.start")

    def end_interaction(self) -> None:
        """Mark end of interaction session."""
        duration_ms = self.get_total_duration_ms()
        self.start_time = 0
        self.logger.event("ptt.interaction.end", duration_ms=duration_ms)